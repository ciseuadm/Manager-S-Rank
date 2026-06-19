from .db import init_db, close_db, get_db
from .models import (
    get_chat_settings, update_chat_setting, set_chat_title,
    get_or_create_user, increment_messages, update_user_rank,
    add_messages, claim_daily, credit_invite, get_top_inviters,
    add_warn, remove_warn, reset_warns, get_warn_history,
    mute_user, unmute_user, clear_expired_mutes, ban_user, unban_user,
    add_blacklist_word, remove_blacklist_word, get_blacklist_words,
    increment_stat, get_chat_stats, get_top_users,
    get_top_moderators, get_chat_activity_summary,
    get_all_chats, get_global_stats, remove_chat,
)
from .economy import (
    get_wallet, get_wallet_balance, add_mana, spend_mana, revert_mana,
    can_reward_message, mark_message_reward, get_top_mana, get_mana_emission,
    mana_emission_by_reason, got_reason_today,
    claim_dungeon, get_wallet_rank, set_wallet_rank,
    get_xp, add_xp, sub_xp,
)
from .referrals import (
    add_referral, count_referrals, count_bot_referrals,
    add_referral_goal, get_referral_goals, deactivate_goal,
    set_chat_role, get_chat_role, mark_referral_rewarded,
    get_unrewarded_referral, mark_all_referrals_rewarded,
    get_primary_referral, set_referral_paid_rank,
    has_goal_award, record_goal_award,
)
from .guilds import (
    get_guild, get_or_create_guild, set_guild_name, set_guild_blocks,
    guild_member_count, guild_rank_counts, top_guilds,
)
from .ad_requests import (
    create_ad_request, get_ad_request, list_ad_requests, set_ad_request_status,
    mark_ad_request_paid,
)
from .ads import (
    create_campaign, get_active_campaigns, get_all_campaigns, get_campaign,
    set_campaign_status, delete_campaign, mark_campaign_sent, log_impression,
    impressions_today, campaign_stats, ads_global_stats,
)
from .payments import (
    add_payment, get_payment_by_charge, payments_total,
    set_payment_status, get_user_last_payment,
)
from .triggers import (
    add_trigger, remove_trigger, list_triggers, count_triggers,
)
from .notes import (
    save_note, get_note, delete_note, list_notes,
)
from .antimat import (
    add_whitelist_word, remove_whitelist_word, get_whitelist_words,
)
from .social import (
    create_clan, get_clan, get_clan_by_name, get_user_clan, join_clan,
    leave_clan, clan_member_count, add_clan_treasury, top_clans,
    get_marriage, create_marriage, divorce,
)
from .tasks import (
    create_task, get_task, get_active_tasks, list_tasks, set_task_active,
    task_completions_count, get_completion, get_completed_task_ids,
    count_user_credited_subs, count_user_completions_today,
    record_completion, get_credited_channel_completions, mark_completion_reverted,
    mark_completion_released, end_task_sponsorship,
    get_user_channel_task_completions,
    get_completion_by_id, list_pending_completions, set_completion_status,
    has_pending_completion,
    create_payout_request, get_payout_request, list_payout_requests, set_payout_status,
    payout_cost_summary, sponsor_revenue_cents,
    has_achievement, count_achievement, award_achievement,
    award_achievement_capped, get_user_achievements,
)

__all__ = [
    "init_db", "close_db", "get_db",
    "get_chat_settings", "update_chat_setting", "set_chat_title",
    "get_or_create_user", "increment_messages", "update_user_rank",
    "add_messages", "claim_daily", "credit_invite", "get_top_inviters",
    "add_warn", "remove_warn", "reset_warns", "get_warn_history",
    "mute_user", "unmute_user", "clear_expired_mutes", "ban_user", "unban_user",
    "add_blacklist_word", "remove_blacklist_word", "get_blacklist_words",
    "increment_stat", "get_chat_stats", "get_top_users",
    "get_top_moderators", "get_chat_activity_summary",
    "get_all_chats", "get_global_stats", "remove_chat",
    # economy
    "get_wallet", "get_wallet_balance", "add_mana", "spend_mana", "revert_mana",
    "can_reward_message", "mark_message_reward", "get_top_mana", "get_mana_emission",
    "mana_emission_by_reason", "got_reason_today",
    "claim_dungeon", "get_wallet_rank", "set_wallet_rank",
    # referrals
    "add_referral", "count_referrals", "count_bot_referrals",
    "add_referral_goal", "get_referral_goals", "deactivate_goal",
    "set_chat_role", "get_chat_role", "mark_referral_rewarded",
    "get_unrewarded_referral", "mark_all_referrals_rewarded",
    "get_primary_referral", "set_referral_paid_rank",
    "has_goal_award", "record_goal_award",
    # chat acquisition (owner-рефералка)
    "get_xp", "add_xp", "sub_xp",
    # guilds
    "get_guild", "get_or_create_guild", "set_guild_name", "set_guild_blocks",
    "guild_member_count", "guild_rank_counts", "top_guilds",
    # ad requests
    "create_ad_request", "get_ad_request", "list_ad_requests", "set_ad_request_status",
    "mark_ad_request_paid",
    # ads
    "create_campaign", "get_active_campaigns", "get_all_campaigns", "get_campaign",
    "set_campaign_status", "delete_campaign", "mark_campaign_sent", "log_impression",
    "impressions_today", "campaign_stats", "ads_global_stats",
    # payments
    "add_payment", "get_payment_by_charge", "payments_total",
    "set_payment_status", "get_user_last_payment",
    # triggers / notes / antimat / social
    "add_trigger", "remove_trigger", "list_triggers", "count_triggers",
    "save_note", "get_note", "delete_note", "list_notes",
    "add_whitelist_word", "remove_whitelist_word", "get_whitelist_words",
    "create_clan", "get_clan", "get_clan_by_name", "get_user_clan", "join_clan",
    "leave_clan", "clan_member_count", "add_clan_treasury", "top_clans",
    "get_marriage", "create_marriage", "divorce",
    # tasks
    "create_task", "get_task", "get_active_tasks", "list_tasks", "set_task_active",
    "task_completions_count", "get_completion", "get_completed_task_ids",
    "count_user_credited_subs", "count_user_completions_today",
    "record_completion", "get_credited_channel_completions", "mark_completion_reverted",
    "mark_completion_released", "end_task_sponsorship",
    "get_user_channel_task_completions",
    "get_completion_by_id", "list_pending_completions", "set_completion_status",
    "has_pending_completion",
    "create_payout_request", "get_payout_request", "list_payout_requests", "set_payout_status",
    "payout_cost_summary", "sponsor_revenue_cents",
    "has_achievement", "count_achievement", "award_achievement",
    "award_achievement_capped", "get_user_achievements",
]
