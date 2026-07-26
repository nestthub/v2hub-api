from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

import src.db.session as db_session_module
from celery import Task
from sqlalchemy import select
from src.core.enums import SourceType
from src.db.models import Source
from src.db.session import get_db_session
from src.services.cache_service import CacheService, get_redis_client
from src.utils.http_client import SubscriptionHTTPClient
from worker.celery_app import app as celery_app

logger = logging.getLogger(__name__)

MAX_CONCURRENT_FETCHES = 10


@asynccontextmanager
async def _session_scope():
    agen = get_db_session()
    session = await anext(agen)

    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await agen.aclose()


async def _close_redis(redis: Any) -> None:
    close_method = getattr(redis, "aclose", None) or getattr(redis, "close", None)
    if callable(close_method):
        result = close_method()
        if asyncio.iscoroutine(result):
            await result


async def _dispose_db_engine() -> None:
    engine = getattr(db_session_module, "engine", None) or getattr(
        db_session_module, "async_engine", None
    )
    if engine is None:
        return

    dispose = getattr(engine, "dispose", None)
    if not callable(dispose):
        return

    result = dispose()
    if asyncio.iscoroutine(result):
        await result


@celery_app.task(
    name="worker.tasks.refresh_external.refresh_all_external_urls",
    bind=True,
    max_retries=0,
    soft_time_limit=840,
    time_limit=870,
)
def refresh_all_external_urls(self: Task) -> dict:
    try:
        return asyncio.run(_refresh_all_async())
    except Exception as e:
        logger.exception("Error in refresh task")
        return {
            "refreshed": 0,
            "failed": 0,
            "total": 0,
            "error": str(e),
        }


async def _refresh_all_async() -> dict:
    redis = None
    try:
        urls = await _collect_external_urls()

        if not urls:
            logger.info("No external URLs to refresh")
            return {"refreshed": 0, "failed": 0, "total": 0}

        logger.info("Starting refresh of %d external URL(s)", len(urls))

        redis = await get_redis_client()
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

        async with SubscriptionHTTPClient() as http_client:

            async def limited_refresh(url: str) -> bool:
                async with semaphore:
                    return await _refresh_one_url(url, redis, http_client)

            results = await asyncio.gather(
                *(limited_refresh(url) for url in urls),
                return_exceptions=True,
            )

        refreshed = 0
        failed = 0

        for result in results:
            if isinstance(result, Exception):
                failed += 1
            elif result:
                refreshed += 1
            else:
                failed += 1

        logger.info(
            "External URL refresh completed: %d succeeded, %d failed, %d total",
            refreshed,
            failed,
            len(urls),
        )

        return {
            "refreshed": refreshed,
            "failed": failed,
            "total": len(urls),
        }

    finally:
        if redis is not None:
            try:
                await _close_redis(redis)
            except Exception:
                logger.exception("Failed to close Redis client")

        try:
            await _dispose_db_engine()
        except Exception:
            logger.exception("Failed to dispose DB engine")


async def _collect_external_urls() -> list[str]:
    try:
        async with _session_scope() as session:
            stmt = (
                select(Source.external_url)
                .where(
                    Source.source_type == SourceType.EXTERNAL_URL.value,
                    Source.external_url.isnot(None),
                )
                .distinct()
            )

            result = await session.execute(stmt)
            urls = [row[0] for row in result.all()]

            logger.debug("Collected %d unique external URLs", len(urls))
            return urls

    except Exception:
        logger.exception("Error collecting external URLs")
        return []


async def _refresh_one_url(url: str, redis: Any, http_client: SubscriptionHTTPClient) -> bool:
    try:
        async with _session_scope() as session:
            cache_service = CacheService(session, redis, http_client)
            content = await cache_service.refresh(url)

        if not content:
            logger.warning("No content returned for %s", url)
            return False

        logger.debug("Successfully refreshed %s", url)
        return True

    except Exception:
        logger.exception("Failed to refresh %s", url)
        return False
