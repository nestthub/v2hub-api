from datetime import datetime, timedelta, UTC
from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.db.repositories.stats_repository import StatsRepository
from v2hub_api.schemas.admin_models.stats import GeneralStats, ProviderStats, StatsResponse

class StatsService:
    """Service handling business logic for API statistics."""
    
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.stats_repo = StatsRepository(session)

    def _calculate_date_range(
        self, 
        start_date: datetime | None, 
        end_date: datetime | None, 
        period: str | None
    ) -> tuple[datetime, datetime]:
        """Translates user inputs into concrete start and end timestamps."""
        now = datetime.now(UTC)
        
        if start_date and end_date:
            return start_date, end_date
            
        if period == "day":
            return now - timedelta(days=1), now
        elif period == "week":
            return now - timedelta(weeks=1), now
        elif period == "month":
            return now - timedelta(days=30), now
            
        # Default fallback: Beginning of time until now
        return datetime.min.replace(tzinfo=UTC), now

    async def get_statistics(
        self, 
        start_date: datetime | None = None, 
        end_date: datetime | None = None, 
        period: str | None = None
    ) -> StatsResponse:
        """Fetches metrics and packages them into the required JSON schema."""
        
        # 1. Figure out the dates
        calc_start, calc_end = self._calculate_date_range(start_date, end_date, period)

        # 2. Run database queries sequentially (SQLAlchemy requires this for a single session)
        total_users = await self.stats_repo.get_total_users()
        new_users = await self.stats_repo.get_new_users(calc_start, calc_end)
        new_subs = await self.stats_repo.get_new_subscriptions(calc_start, calc_end)
        new_providers = await self.stats_repo.get_new_providers(calc_start, calc_end)
        active_providers = await self.stats_repo.get_active_providers()
        connected_users = await self.stats_repo.get_users_connected_to_providers()

        # 3. Package the results into our Pydantic Schema
        return StatsResponse(
            general=GeneralStats(
                total_users=total_users,
                new_users=new_users,
                new_subscriptions=new_subs,
                new_providers=new_providers
            ),
            providers=ProviderStats(
                active_providers=active_providers,
                users_connected_to_providers=connected_users
            )
        )