"""
Ad delivery service.

Sends active ad campaigns to chats once per day, never exceeding the per-chat
daily cap (1/day by default). Uses the safe broadcaster for rate-limiting and
dead-chat cleanup. Each text ad is labelled "📢 Реклама" to stay within
Telegram's advertising rules.
"""
from datetime import date

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger

from database import (
    get_active_campaigns, get_campaign, get_all_chats, get_chat_settings,
    impressions_today, log_impression, mark_campaign_sent,
)
from services.broadcaster import broadcast
from utils import get_config, ce, strip_custom_emoji


def _ad_markup(camp: dict) -> InlineKeyboardMarkup | None:
    if camp.get("button_text") and camp.get("button_url"):
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=camp["button_text"], url=camp["button_url"])
        ]])
    return None


async def _deliver(bot: Bot, chat_id: int, camp: dict, *, is_channel: bool = False) -> None:
    """Send one ad to one chat. Raises on failure (so broadcaster counts it).

    Премиум-эмодзи в тексте рекламы работают в группах/супергруппах (Premium у
    владельца). В КАНАЛЕ бот не может показать кастом-эмодзи (ограничение Telegram,
    Bot API 9.4) — поэтому для канала снимаем теги заранее, чтобы не слать заведомо
    отклоняемый запрос. Кнопки (reply_markup) работают везде, включая канал.
    """
    markup = _ad_markup(camp)
    if camp.get("content_type") == "copy":
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=camp["from_chat_id"],
            message_id=camp["from_msg_id"],
            reply_markup=markup,
        )
    else:
        text = f"{ce('megaphone')} <b>Реклама</b>\n\n" + (camp.get("payload") or "")
        if is_channel:
            text = strip_custom_emoji(text)
        await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup,
                               disable_web_page_preview=False)


async def _eligible_chats(cfg) -> list[int]:
    """Chats that allow ads and haven't hit their daily cap yet."""
    out = []
    for c in await get_all_chats():
        cid = c["chat_id"]
        s = await get_chat_settings(cid)
        if not s.get("ads_enabled", 1):
            continue
        if await impressions_today(cid) >= cfg.ads_daily_limit_per_chat:
            continue
        out.append(cid)
    return out


async def send_campaign(bot: Bot, camp: dict) -> dict:
    """Deliver a single campaign to all eligible chats (or the channel)."""
    cfg = get_config()
    today = date.today().isoformat()

    if camp.get("target") == "channel":
        if not cfg.bot_channel_id:
            logger.warning("[ADS] channel target but BOT_CHANNEL_ID is empty")
            return {"sent": 0, "failed": 0, "removed": 0}
        try:
            await _deliver(bot, cfg.bot_channel_id, camp, is_channel=True)
            await log_impression(camp["id"], cfg.bot_channel_id, "sent")
            result = {"sent": 1, "failed": 0, "removed": 0}
        except Exception as e:
            logger.warning(f"[ADS] channel send failed: {e}")
            await log_impression(camp["id"], cfg.bot_channel_id, "failed")
            result = {"sent": 0, "failed": 1, "removed": 0}
        await mark_campaign_sent(camp["id"], today)
        return result

    chats = await _eligible_chats(cfg)

    async def send_fn(b: Bot, cid: int, camp=camp) -> None:
        await _deliver(b, cid, camp)
        await log_impression(camp["id"], cid, "sent")

    result = await broadcast(bot, chats, send_fn)
    await mark_campaign_sent(camp["id"], today)
    logger.info(f"[ADS] campaign #{camp['id']} delivered: {result}")
    return result


async def send_due_ads(bot: Bot) -> dict:
    """Daily job: send every active campaign that hasn't been sent today."""
    cfg = get_config()
    if not cfg.ads_enabled:
        return {"campaigns": 0}
    today = date.today().isoformat()
    campaigns = await get_active_campaigns()
    total = {"campaigns": 0, "sent": 0, "failed": 0, "removed": 0}
    for camp in campaigns:
        if camp.get("last_sent_date") == today:
            continue
        r = await send_campaign(bot, camp)
        total["campaigns"] += 1
        for k in ("sent", "failed", "removed"):
            total[k] += r.get(k, 0)
    logger.info(f"[ADS] daily run: {total}")
    return total


async def send_campaign_now(bot: Bot, campaign_id: int) -> dict:
    """Manually push a campaign immediately (respects per-chat daily cap)."""
    camp = await get_campaign(campaign_id)
    if not camp:
        return {"error": "not_found"}
    return await send_campaign(bot, camp)
