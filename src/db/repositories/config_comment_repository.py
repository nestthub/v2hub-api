from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ConfigComment

from src.db.repositories.base import BaseRepository



# ═══════════════════════════════════════════════════════════════════════════
# ConfigComment Repository
# ═══════════════════════════════════════════════════════════════════════════

class ConfigCommentRepository(BaseRepository[ConfigComment]):
    """Repository for ConfigComment model operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(ConfigComment, session)
    
    async def get_comment(
        self,
        subscription_token: str,
        config_hash: str
    ) -> Optional[ConfigComment]:
        """Get comment for a specific config in a subscription."""
        stmt = select(ConfigComment).where(
            ConfigComment.subscription_token == subscription_token,
            ConfigComment.config_hash == config_hash
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_all_for_subscription(
        self,
        subscription_token: str
    ) -> List[ConfigComment]:
        """Get all comments for a subscription."""
        stmt = select(ConfigComment).where(
            ConfigComment.subscription_token == subscription_token
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def upsert_comment(
        self,
        subscription_token: str,
        config_hash: str,
        comment: str
    ) -> ConfigComment:
        """Create or update a config comment."""
        existing = await self.get_comment(subscription_token, config_hash)
        
        if existing:
            return await self.update(existing, comment=comment)
        
        return await self.create(
            subscription_token=subscription_token,
            config_hash=config_hash,
            comment=comment
        )
    
    async def delete_for_subscription(
        self,
        subscription_token: str,
        config_hash: Optional[str] = None
    ) -> int:
        """
        Delete comments for a subscription.
        
        Args:
            subscription_token: Subscription token
            config_hash: Specific config hash (if None, deletes all)
            
        Returns:
            Number of deleted records
        """
        stmt = delete(ConfigComment).where(
            ConfigComment.subscription_token == subscription_token
        )
        
        if config_hash:
            stmt = stmt.where(ConfigComment.config_hash == config_hash)
        
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount
