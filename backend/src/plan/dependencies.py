from src.auth.dependencies import CurrentUser
from src.config import settings
from src.rate_limit import check_rate_limit


# per user, because AI calls cost money per user; plan and chat will share it
async def ai_rate_limit(user: CurrentUser) -> None:
    await check_rate_limit(f"ai:{user.id}", settings.ai_rate_limit_per_minute)
