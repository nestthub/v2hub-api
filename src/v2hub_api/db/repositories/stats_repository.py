from datetime import datetime
from sqlalchemy import func, select, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.db.models import User, Subscription, ProxyConfig, Source

class StatsRepository:
    """Repository for aggregating business statistics directly in the database."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_total_users(self) -> int:
        result = await self.session.execute(select(func.count(User.user_hash)))
        return result.scalar_one()

    async def get_new_users(self, start_date: datetime, end_date: datetime) -> int:
        stmt = select(func.count(User.user_hash)).where(
            User.created_at >= start_date,
            User.created_at <= end_date
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_new_subscriptions(self, start_date: datetime, end_date: datetime) -> int:
        stmt = select(func.count(Subscription.token)).where(
            Subscription.created_at >= start_date,
            Subscription.created_at <= end_date
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_new_providers(self, start_date: datetime, end_date: datetime) -> int:
        stmt = select(func.count(ProxyConfig.config_hash)).where(
            ProxyConfig.created_at >= start_date,
            ProxyConfig.created_at <= end_date
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_active_providers(self) -> int:
        result = await self.session.execute(select(func.count(ProxyConfig.config_hash)))
        return result.scalar_one()

    async def get_users_connected_to_providers(self) -> int:
        # Count distinct users who have at least one valid source in their subscriptions
        stmt = (
            select(func.count(distinct(Subscription.user_hash)))
            .select_from(Subscription)
            .join(Source, Subscription.token == Source.subscription_token)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()