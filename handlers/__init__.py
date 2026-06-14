from .moderation import router as moderation_router, set_bot_id
from .admin import router as admin_router
from .user import router as user_router
from .settings import router as settings_router
from .owner import router as owner_router
from .economy import router as economy_router

__all__ = [
    "moderation_router", "admin_router", "user_router", "settings_router",
    "owner_router", "economy_router", "set_bot_id",
]
