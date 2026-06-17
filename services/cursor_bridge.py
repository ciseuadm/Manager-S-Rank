"""
Cursor-мост: запускает агента Cursor SDK прямо в папке этого проекта, чтобы
владелец мог из лички Telegram-бота отправлять задачи («обнови X», «почини Y»),
а агент реально правил код проекта и возвращал ответ.

Архитектура:
  • Один локальный bridge-клиент (cursor-sdk-bridge) на весь процесс бота,
    поднимается лениво при первом обращении и закрывается на остановке бота.
  • Один «диалог» (AsyncAgent) на активную сессию: первое сообщение создаёт
    агента, последующие — это follow-up в тот же диалог (удобно для мелких
    фиксов). Кнопка «Новый диалог» сбрасывает агента.
  • Задачи сериализуются (один запуск за раз) — Lock + флаг busy.

Без CURSOR_API_KEY или без установленного cursor_sdk мост просто «недоступен»,
а весь остальной бот работает как обычно (graceful degradation).

Модели:
  auto  → сервер Cursor сам выбирает ИИ (по умолчанию);
  sonnet/opus → конкретная модель (ID берём из конфига/списка моделей);
  max   → сильная модель + параметр «Max Mode» (ищем его в list_models).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Optional

from loguru import logger

# Корень проекта = папка на уровень выше services/
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])

MODEL_CHOICES = ("auto", "sonnet", "opus", "max")
MODEL_LABELS = {
    "auto": "🎲 Auto (Cursor сам выбирает)",
    "sonnet": "⚡ Sonnet 4.6",
    "opus": "🧠 Opus 4.8",
    "max": "🚀 MAX (для крупных задач)",
}


def sdk_installed() -> bool:
    try:
        import cursor_sdk  # noqa: F401
        return True
    except Exception:
        return False


class CursorBridge:
    def __init__(self) -> None:
        self._client: Any = None
        self._agent: Any = None
        self._models_cache: Optional[list] = None
        self._lock = asyncio.Lock()
        self._api_key: str = ""
        self.active: bool = False
        self.busy: bool = False
        self.model_choice: str = "auto"

    # ── Конфигурация ─────────────────────────────────────────────────────────

    def configure(self, api_key: str, model_sonnet: str = "", model_opus: str = "") -> None:
        self._api_key = (api_key or "").strip()
        self._model_sonnet = model_sonnet or "claude-4.6-sonnet"
        self._model_opus = model_opus or "claude-opus-4.8"

    def available(self) -> bool:
        """Мост можно использовать только если есть SDK и ключ."""
        return sdk_installed() and bool(self._api_key)

    def status_text(self) -> str:
        if not sdk_installed():
            return (
                "⚠️ Пакет <code>cursor-sdk</code> не установлен.\n"
                "Установи: <code>pip install cursor-sdk</code>"
            )
        if not self._api_key:
            return (
                "⚠️ Не задан <code>CURSOR_API_KEY</code> в .env.\n"
                "Возьми ключ тут: https://cursor.com/dashboard/integrations "
                "и впиши в .env, затем перезапусти бота."
            )
        state = "🟢 включён" if self.active else "⚪️ выключен"
        return (
            f"🛰 <b>Cursor-мост</b>: {state}\n"
            f"Модель: <b>{MODEL_LABELS.get(self.model_choice, self.model_choice)}</b>\n"
            f"Проект: <code>{PROJECT_ROOT}</code>"
        )

    # ── Жизненный цикл клиента/агента ──────────────────────────────────────────

    async def _ensure_client(self):
        if self._client is not None:
            return self._client
        from cursor_sdk import AsyncClient, LocalAgentOptions

        # Ключ кладём в окружение, чтобы bridge-процесс и клиент его подхватили.
        if self._api_key:
            os.environ.setdefault("CURSOR_API_KEY", self._api_key)
        logger.info(f"[CURSOR] launching bridge in {PROJECT_ROOT}")
        self._client = await AsyncClient.launch_bridge(
            workspace=PROJECT_ROOT,
            local=LocalAgentOptions(cwd=PROJECT_ROOT),
        )
        return self._client

    async def _list_models(self) -> list:
        if self._models_cache is not None:
            return self._models_cache
        try:
            client = await self._ensure_client()
            self._models_cache = list(await client.list_models())
        except Exception as e:
            logger.warning(f"[CURSOR] list_models failed: {e}")
            self._models_cache = []
        return self._models_cache

    def _find_model(self, models: list, *needles: str):
        """Найти SDKModel по подстроке в id/display_name."""
        for m in models:
            hay = f"{getattr(m, 'id', '')} {getattr(m, 'display_name', '')}".lower()
            if all(n.lower() in hay for n in needles):
                return m
        return None

    async def _resolve_model(self, choice: str):
        """Вернуть значение для аргумента model (str | ModelSelection)."""
        if choice == "auto":
            return "auto"

        from cursor_sdk import ModelSelection, ModelParameterValue

        models = await self._list_models()

        if choice in ("opus", "max"):
            target_id = self._model_opus
            model_obj = self._find_model(models, "opus") if models else None
        else:  # sonnet
            target_id = self._model_sonnet
            model_obj = self._find_model(models, "sonnet") if models else None

        model_id = getattr(model_obj, "id", None) or target_id

        if choice != "max":
            # Plain Sonnet/Opus → серверный дефолт-вариант модели.
            return ModelSelection(id=model_id)

        # MAX = тяжёлый режим: effort=max, максимальный context (1m), thinking=on.
        # Собираем по реальной схеме параметров модели (id 'effort'/'context'/
        # 'thinking'), не хардкодя значения сверх известной семантики.
        params = []
        if model_obj is not None:
            for pdef in getattr(model_obj, "parameters", []) or []:
                pid = (getattr(pdef, "id", "") or "").lower()
                values = [getattr(v, "value", None) for v in (getattr(pdef, "values", []) or [])]
                values = [v for v in values if v is not None]
                if not values:
                    continue
                chosen = None
                if pid == "effort":
                    chosen = "max" if "max" in values else values[-1]
                elif pid == "context":
                    chosen = values[-1]  # самое большое окно контекста
                elif pid == "thinking":
                    chosen = "true" if "true" in values else values[-1]
                if chosen is not None:
                    params.append(ModelParameterValue(id=getattr(pdef, "id"), value=chosen))
        return ModelSelection(id=model_id, params=params)

    async def _ensure_agent(self):
        if self._agent is not None:
            return self._agent
        from cursor_sdk import AsyncAgent, LocalAgentOptions

        client = await self._ensure_client()
        model = await self._resolve_model(self.model_choice)
        logger.info(f"[CURSOR] creating agent model={self.model_choice}")
        self._agent = await AsyncAgent.create(
            client=client,
            model=model,
            api_key=self._api_key or None,
            # setting_sources="all" → агент уважает .cursor/rules и docs/GOAL.md
            # этого проекта (важно, чтобы фиксы шли в стиле проекта).
            local=LocalAgentOptions(cwd=PROJECT_ROOT, setting_sources=["all"]),
        )
        return self._agent

    # ── Публичные операции ─────────────────────────────────────────────────────

    def start_session(self) -> None:
        self.active = True

    async def stop_session(self) -> None:
        self.active = False
        await self._reset_agent()

    async def _reset_agent(self) -> None:
        agent = self._agent
        self._agent = None
        if agent is not None:
            try:
                await agent.close()
            except Exception:
                pass

    async def new_dialog(self) -> None:
        """Сбросить текущий диалог — следующее сообщение начнёт новый."""
        await self._reset_agent()

    async def set_model(self, choice: str) -> None:
        if choice not in MODEL_CHOICES:
            return
        if choice != self.model_choice:
            self.model_choice = choice
            # Модель применяется при создании агента → сбрасываем текущий диалог.
            await self._reset_agent()

    async def run_task(self, prompt: str) -> tuple[bool, str]:
        """
        Отправить задачу агенту и дождаться результата.
        Возвращает (ok, text). ok=False — ошибка запуска/выполнения.
        """
        if self.busy:
            return False, "⏳ Агент сейчас занят другой задачей. Дождись ответа."
        from cursor_sdk import CursorAgentError

        async with self._lock:
            self.busy = True
            try:
                agent = await self._ensure_agent()
                run = await agent.send(prompt)
                logger.info(f"[CURSOR] run started: {getattr(run, 'run_id', '?')}")
                result = await run.wait()
                status = str(getattr(result, "status", "") or "").lower()
                text = (getattr(result, "result", "") or "").strip()
                if status and status not in ("finished", "completed", "success", "done"):
                    logger.warning(f"[CURSOR] run status={status}")
                    return False, text or f"Агент завершился со статусом: {status}"
                return True, text or "(агент завершил работу без текстового ответа)"
            except CursorAgentError as e:
                logger.warning(f"[CURSOR] startup error: {e}")
                # При фатальной ошибке клиента/диалога — сбросим, чтобы пересоздать.
                await self._reset_agent()
                self._client = None
                return False, f"Не удалось запустить агента: {e}"
            except Exception as e:
                logger.exception(f"[CURSOR] run failed: {e}")
                await self._reset_agent()
                return False, f"Ошибка во время выполнения: {e}"
            finally:
                self.busy = False

    async def list_models_text(self) -> str:
        models = await self._list_models()
        if not models:
            return "Не удалось получить список моделей (проверь ключ и сеть)."
        lines = ["🤖 <b>Доступные модели Cursor</b>\n"]
        for m in models[:40]:
            mid = getattr(m, "id", "?")
            dn = getattr(m, "display_name", "") or ""
            # Помечаем модели, поддерживающие effort=max (наш режим MAX).
            has_max = any(
                (getattr(p, "id", "") or "").lower() == "effort"
                and any(getattr(v, "value", None) == "max" for v in (getattr(p, "values", []) or []))
                for p in (getattr(m, "parameters", []) or [])
            )
            lines.append(f"• <code>{mid}</code> — {dn}{' · MAX' if has_max else ''}")
        return "\n".join(lines)

    async def close(self) -> None:
        await self._reset_agent()
        client = self._client
        self._client = None
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                try:
                    client.shutdown()
                except Exception:
                    pass


# Singleton на весь процесс бота.
bridge = CursorBridge()
