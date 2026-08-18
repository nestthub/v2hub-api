"""
Admin API router.

Aggregates internal administrative endpoints for:
- User management
- Provider management
- IP ban management
- IP whitelist management
- Platform statistics

All admin endpoints are protected by the security dependencies
defined in the admin dependencies module.
"""

from fastapi import APIRouter

from . import bans, providers, stats, users, whitelist

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    include_in_schema=False,
)

router.include_router(users.router)
router.include_router(providers.router)
router.include_router(bans.router)
router.include_router(whitelist.router)
router.include_router(stats.router)
