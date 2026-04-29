"""
Whitelist service for managing IP addresses exempt from rate limiting.

Uses Redis for distributed whitelist storage.
"""

import logging
from datetime import datetime
from typing import List, Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class WhitelistService:
    """
    Service for managing whitelisted IP addresses.
    
    Features:
    - Add/remove IPs from whitelist
    - Check if IP is whitelisted
    - Support for CIDR notation
    - Persistent storage in Redis
    """
    
    def __init__(self, redis_client: redis.Redis):
        """
        Initialize whitelist service.
        
        Args:
            redis_client: Redis client for storage
        """
        self.redis = redis_client
        self.whitelist_key = "whitelist:ips"
        self.whitelist_meta_prefix = "whitelist:meta:"
    
    async def is_whitelisted(self, ip: str) -> bool:
        """
        Check if an IP is whitelisted.
        
        Args:
            ip: IP address to check
            
        Returns:
            True if whitelisted, False otherwise
        """
        try:
            # Check exact match
            is_member = await self.redis.sismember(self.whitelist_key, ip)
            
            if is_member:
                return True
            
            # Check CIDR ranges
            all_entries = await self.redis.smembers(self.whitelist_key)
            
            for entry in all_entries:
                entry_str = entry.decode('utf-8') if isinstance(entry, bytes) else entry
                
                # If entry contains '/', it's a CIDR range
                if '/' in entry_str:
                    if self._ip_in_cidr(ip, entry_str):
                        return True
            
            return False
        
        except Exception as e:
            logger.error(f"Error checking whitelist for {ip}: {e}")
            # Fail open - don't block on Redis errors
            return False
    
    def _ip_in_cidr(self, ip: str, cidr: str) -> bool:
        """
        Check if IP is in CIDR range.
        
        Args:
            ip: IP address to check
            cidr: CIDR notation (e.g., "10.0.0.0/24")
            
        Returns:
            True if IP is in range
        """
        try:
            import ipaddress
            
            ip_obj = ipaddress.ip_address(ip)
            network = ipaddress.ip_network(cidr, strict=False)
            
            return ip_obj in network
        
        except Exception as e:
            logger.error(f"Error checking CIDR {cidr} for {ip}: {e}")
            return False
    
    async def add(self, ip_address: str, description: Optional[str] = None) -> bool:
        """
        Add IP to whitelist.
        
        Args:
            ip_address: IP address or CIDR to whitelist
            description: Optional description
            
        Returns:
            True if added, False if already existed
        """
        try:
            # Validate IP/CIDR format
            import ipaddress
            
            if '/' in ip_address:
                # Validate CIDR
                ipaddress.ip_network(ip_address, strict=False)
            else:
                # Validate IP
                ipaddress.ip_address(ip_address)
            
            # Add to set
            added = await self.redis.sadd(self.whitelist_key, ip_address)
            
            # Store metadata
            if description:
                meta_key = f"{self.whitelist_meta_prefix}{ip_address}"
                await self.redis.hset(
                    meta_key,
                    mapping={
                        "description": description,
                        "added_at": datetime.now().isoformat(),
                    }
                )
            
            logger.info(
                f"IP added to whitelist: {ip_address} (%s)",
                description or "no description"
            )
            
            return bool(added)
        
        except Exception as e:
            logger.error(f"Error adding {ip_address} to whitelist: {e}")
            raise
    
    async def remove(self, ip_address: str) -> bool:
        """
        Remove IP from whitelist.
        
        Args:
            ip_address: IP address to remove
            
        Returns:
            True if removed, False if didn't exist
        """
        try:
            # Remove from set
            removed = await self.redis.srem(self.whitelist_key, ip_address)
            
            # Remove metadata
            meta_key = f"{self.whitelist_meta_prefix}{ip_address}"
            await self.redis.delete(meta_key)
            
            logger.info(f"IP removed from whitelist: {ip_address}")
            
            return bool(removed)
        
        except Exception as e:
            logger.error(f"Error removing {ip_address} from whitelist: {e}")
            raise
    
    async def list_all(self) -> List[dict]:
        """
        Get all whitelisted IPs with metadata.
        
        Returns:
            List of whitelist entries
        """
        try:
            entries = await self.redis.smembers(self.whitelist_key)
            
            result = []
            for entry in entries:
                ip_address = entry.decode('utf-8') if isinstance(entry, bytes) else entry
                
                # Get metadata
                meta_key = f"{self.whitelist_meta_prefix}{ip_address}"
                meta = await self.redis.hgetall(meta_key)
                
                description = None
                added_at = datetime.now().isoformat()
                
                if meta:
                    description = meta.get(b"description")
                    if description:
                        description = description.decode('utf-8')
                    
                    added_at_bytes = meta.get(b"added_at")
                    if added_at_bytes:
                        added_at = added_at_bytes.decode('utf-8')
                
                result.append({
                    "ip_address": ip_address,
                    "description": description,
                    "added_at": added_at,
                })
            
            return sorted(result, key=lambda x: x["added_at"], reverse=True)
        
        except Exception as e:
            logger.error(f"Error listing whitelist: {e}")
            return []
    
    async def clear(self) -> int:
        """
        Clear all whitelisted IPs.
        
        Returns:
            Number of IPs removed
        """
        try:
            # Get all entries first for metadata cleanup
            entries = await self.redis.smembers(self.whitelist_key)
            
            # Delete metadata for each entry
            for entry in entries:
                ip_address = entry.decode('utf-8') if isinstance(entry, bytes) else entry
                meta_key = f"{self.whitelist_meta_prefix}{ip_address}"
                await self.redis.delete(meta_key)
            
            # Delete the set
            count = await self.redis.delete(self.whitelist_key)
            
            logger.info(f"Whitelist cleared: {len(entries)} entries removed")
            
            return len(entries)
        
        except Exception as e:
            logger.error(f"Error clearing whitelist: {e}")
            raise


# Global whitelist service instance
_whitelist_service: Optional[WhitelistService] = None


async def get_whitelist_service() -> Optional[WhitelistService]:
    """Get global whitelist service instance."""
    global _whitelist_service
    
    if _whitelist_service is None:
        # Import here to avoid circular dependency
        from src.services.cache_service import get_redis_client
        
        redis_client = await get_redis_client()
        if redis_client:
            _whitelist_service = WhitelistService(redis_client=redis_client)
    
    return _whitelist_service
