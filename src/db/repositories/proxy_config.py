from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ProxyConfig

from src.db.repositories.base import BaseRepository






# ═══════════════════════════════════════════════════════════════════════════
# ProxyConfig Repository
# ═══════════════════════════════════════════════════════════════════════════

class ProxyConfigRepository(BaseRepository[ProxyConfig]):
    """Repository for ProxyConfig model operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(ProxyConfig, session)
    
    async def get_by_hash(self, config_hash: str) -> Optional[ProxyConfig]:
        """Get config by hash."""
        return await self.get_by_id(config_hash)
    
    async def create_config(
        self,
        config_hash: str,
        config_data: str,
        protocol: str
    ) -> ProxyConfig:
        """Create or get existing proxy config."""
        # Check if config already exists
        existing = await self.get_by_hash(config_hash)
        if existing:
            return existing
        
        # Create new config
        return await self.create(
            config_hash=config_hash,
            config_data=config_data,
            protocol=protocol
        )
    
    async def get_or_create(
        self,
        config_hash: str,
        config_data: str,
        protocol: str
    ) -> ProxyConfig:
        """Get existing config or create if doesn't exist."""
        return await self.create_config(config_hash, config_data, protocol)
