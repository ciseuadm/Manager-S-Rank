from .moderation import router as moderation_router, set_bot_id
from .admin import router as admin_router
from .user import router as user_router
from .settings import router as settings_router
from .owner import router as owner_router
from .economy import router as economy_router
from .referral import router as referral_router
from .payments import router as payments_router
from .ads import router as ads_router
from .sponsors import router as sponsors_router
from .tasks import router as tasks_router
from .cursor_link import router as cursor_router
from .fun import router as fun_router
from .menu import router as menu_router

__all__ = [
    "moderation_router", "admin_router", "user_router", "settings_router",
    "owner_router", "economy_router", "referral_router", "payments_router",
    "ads_router", "sponsors_router", "tasks_router", "cursor_router", "fun_router",
    "menu_router", "set_bot_id",
]
