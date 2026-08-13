"""
Subscription management API endpoints.

REST API for:
- Creating subscriptions
- Listing user's subscriptions
- Getting subscription details
- Updating subscription metadata
- Deleting subscriptions
- Managing sources (add, replace, remove)
- Managing config comments
"""

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Depends, status

from v2hub_api.api.dependencies import (
    ResolverServiceDep,
    SubscriptionActor,
    SubscriptionServiceDep,
    get_actor,
    get_provider_actor,
)
from v2hub_api.core.config import settings
from v2hub_api.core.enums import SourceType
from v2hub_api.core.exceptions import to_http_exception
from v2hub_api.db.models import Subscription
from v2hub_api.schemas import (
    RefreshSubscriptionResponse,
    SourceOut,
    SourcesAddRequest,
    SourcesRemoveRequest,
    SourcesReplaceRequest,
    SourceUpdateRequest,
    SubscriptionCreateRequest,
    SubscriptionListItem,
    SubscriptionResponse,
    SubscriptionUpdateRequest,
)

# ═══════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════


def convert_sources_to_out(subscription: Subscription) -> list[SourceOut]:
    """
    Преобразует источники из БД в формат API.

    Для каждого источника формирует поле data:
    - CONFIG: конфиг с комментарием (если есть)
    - EXTERNAL_URL: URL подписки
    - INTERNAL_TOKEN: токен другой подписки
    """
    result = []

    comment_map = {cc.config_hash: cc.comment for cc in subscription.config_comments}

    for source in subscription.sources:
        if source.source_type == SourceType.CONFIG.value and source.config_hash:
            config_data = source.proxy_config.config_data if source.proxy_config else ""
            comment = comment_map.get(source.config_hash)
            data = f"{config_data}#{comment}" if comment else config_data
        elif source.source_type == SourceType.INTERNAL_TOKEN.value and source.internal_token:
            data = f"https://{settings.domain}/sub/{source.internal_token}"
        elif source.source_type == SourceType.EXTERNAL_URL and source.external_url:
            data = source.external_url
        else:
            continue

        result.append(
            SourceOut(
                id=source.id,
                source_type=SourceType(source.source_type),
                data=data,
                order_index=source.order_index,
                is_hidden=source.is_hidden,
                max_depth=source.max_depth,
                created_at=source.created_at,
                updated_at=source.updated_at,
            )
        )

    return result


async def get_total_configs_count(
    subscription_token: str,
    resolver: ResolverServiceDep,
) -> int:
    """
    Получает реальное количество конфигов, включая те что в подписках.

    Использует resolver для разворачивания всех вложенных подписок
    и подсчета уникальных конфигов.
    """
    try:
        result = await resolver.resolve(subscription_token)
        return result.count
    except Exception as e:
        raise to_http_exception(e) from e


async def _to_response(
    subscription: Subscription,
    resolver: ResolverServiceDep,
    provider_name: str | None,
) -> SubscriptionResponse:
    """Shared assembly of a full SubscriptionResponse from a Subscription row."""
    sources_count = await get_total_configs_count(subscription.token, resolver)
    return SubscriptionResponse(
        token=subscription.token,
        name=subscription.name,
        provider_name=provider_name,
        description=subscription.description,
        sources=convert_sources_to_out(subscription),
        sources_count=sources_count,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
    )


def _provider_hash(actor: SubscriptionActor) -> str | None:
    """provider_hash of the acting provider, or None for self-service."""
    return actor.provider.provider_hash if actor.provider else None


def _provider_name(
    actor: SubscriptionActor, subscription: Subscription | None = None
) -> str | None:
    """provider_name of the acting provider, or None for self-service."""
    if actor.provider:
        return actor.provider.provider_name

    if subscription and subscription.provider_hash and subscription.provider:
        return subscription.provider.provider_name

    return None


# ═══════════════════════════════════════════════════════════════════════════
# Router factory
# ═══════════════════════════════════════════════════════════════════════════


def build_subscriptions_router(
    *,
    prefix: str,
    actor_dep: Callable[..., Awaitable[SubscriptionActor]],
    tags: list[str | Enum] | None = None,
) -> APIRouter:
    """
    Строит роутер с полным набором CRUD-ручек подписок.

    :param prefix: "/subscriptions" для self-service пользователя, или
                    "/providers/{user_id}/subscriptions" для провайдера.
    :param actor_dep: dependency, отдающая SubscriptionActor —
                    единственное, что отличает self-service от провайдера.
    :param tags: OpenAPI-теги для этой группы роутов.
    """
    router = APIRouter(prefix=prefix, tags=tags or ["Subscriptions"])
    Actor = Annotated[SubscriptionActor, Depends(actor_dep)]

    # ─────────────────────────── CRUD ───────────────────────────

    @router.post(
        "",
        response_model=SubscriptionResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create subscription",
        description="Create a new subscription with optional initial sources",
    )
    async def create_subscription(
        data: SubscriptionCreateRequest,
        actor: Actor,
        service: SubscriptionServiceDep,
        resolver: ResolverServiceDep,
    ) -> SubscriptionResponse:
        try:
            subscription = await service.create_subscription(
                user_hash=actor.user_hash,
                provider_hash=_provider_hash(actor),
                name=data.name,
                description=data.description,
                sources=data.sources,
            )
            return await _to_response(subscription, resolver, provider_name=_provider_name(actor))
        except Exception as e:
            raise to_http_exception(e) from e

    @router.get(
        "",
        response_model=list[SubscriptionListItem],
        summary="List subscriptions",
        description="List all subscriptions for the target user",
    )
    async def list_subscriptions(
        actor: Actor,
        service: SubscriptionServiceDep,
        resolver: ResolverServiceDep,
    ) -> list[SubscriptionListItem]:
        try:
            subscriptions = await service.list_subscriptions(
                user_hash=actor.user_hash,
                provider_hash=_provider_hash(actor),
            )

            result = []
            for subscription in subscriptions:
                provider_name = _provider_name(actor, subscription)

                sources_count = await get_total_configs_count(subscription.token, resolver)
                result.append(
                    SubscriptionListItem(
                        token=subscription.token,
                        name=subscription.name,
                        provider_name=provider_name,
                        description=subscription.description,
                        sources_count=sources_count,
                        created_at=subscription.created_at,
                        updated_at=subscription.updated_at,
                    )
                )
            return result
        except Exception as e:
            raise to_http_exception(e) from e

    @router.get(
        "/{token}",
        response_model=SubscriptionResponse,
        summary="Get subscription",
        description="Get detailed subscription information including sources",
    )
    async def get_subscription(
        token: str,
        actor: Actor,
        service: SubscriptionServiceDep,
        resolver: ResolverServiceDep,
    ) -> SubscriptionResponse:
        try:
            subscription = await service.get_subscription(
                token=token,
                user_hash=actor.user_hash,
            )
            return await _to_response(
                subscription, resolver, provider_name=_provider_name(actor, subscription)
            )
        except Exception as e:
            raise to_http_exception(e) from e

    @router.patch(
        "/{token}",
        response_model=SubscriptionResponse,
        summary="Update subscription",
        description="Update subscription metadata (name and/or description)",
    )
    async def update_subscription(
        token: str,
        data: SubscriptionUpdateRequest,
        actor: Actor,
        service: SubscriptionServiceDep,
        resolver: ResolverServiceDep,
    ) -> SubscriptionResponse:
        try:
            subscription = await service.update_subscription(
                token=token,
                user_hash=actor.user_hash,
                provider_hash=_provider_hash(actor),
                name=data.name,
                description=data.description,
            )
            return await _to_response(subscription, resolver, provider_name=_provider_name(actor))
        except Exception as e:
            raise to_http_exception(e) from e

    @router.delete(
        "/{token}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Delete subscription",
        description="Delete a subscription and all its sources",
    )
    async def delete_subscription(
        token: str,
        actor: Actor,
        service: SubscriptionServiceDep,
    ) -> None:
        try:
            await service.delete_subscription(
                token=token,
                user_hash=actor.user_hash,
                provider_hash=_provider_hash(actor),
            )
        except Exception as e:
            raise to_http_exception(e) from e

    # ─────────────────────── Source Management ───────────────────────

    @router.post(
        "/{token}/sources",
        response_model=SubscriptionResponse,
        summary="Add sources",
        description="Add new sources to a subscription",
    )
    async def add_sources(
        token: str,
        data: SourcesAddRequest,
        actor: Actor,
        service: SubscriptionServiceDep,
        resolver: ResolverServiceDep,
    ) -> SubscriptionResponse:
        try:
            subscription = await service.add_sources(
                token=token,
                user_hash=actor.user_hash,
                provider_hash=_provider_hash(actor),
                sources=data.sources,
            )
            return await _to_response(subscription, resolver, provider_name=_provider_name(actor))
        except Exception as e:
            raise to_http_exception(e) from e

    @router.put(
        "/{token}/sources",
        response_model=SubscriptionResponse,
        summary="Replace sources",
        description="Replace all sources in a subscription",
    )
    async def replace_sources(
        token: str,
        data: SourcesReplaceRequest,
        actor: Actor,
        service: SubscriptionServiceDep,
        resolver: ResolverServiceDep,
    ) -> SubscriptionResponse:
        try:
            subscription = await service.replace_sources(
                token=token,
                user_hash=actor.user_hash,
                provider_hash=_provider_hash(actor),
                sources=data.sources,
            )
            return await _to_response(subscription, resolver, provider_name=_provider_name(actor))
        except Exception as e:
            raise to_http_exception(e) from e

    @router.delete(
        "/{token}/sources",
        response_model=SubscriptionResponse,
        summary="Remove sources",
        description="Remove specific sources by their IDs",
    )
    async def remove_sources(
        token: str,
        data: SourcesRemoveRequest,
        actor: Actor,
        service: SubscriptionServiceDep,
        resolver: ResolverServiceDep,
    ) -> SubscriptionResponse:
        try:
            subscription = await service.remove_sources(
                token=token,
                user_hash=actor.user_hash,
                provider_hash=_provider_hash(actor),
                source_ids=data.source_ids,
            )
            return await _to_response(subscription, resolver, provider_name=_provider_name(actor))
        except Exception as e:
            raise to_http_exception(e) from e

    # ─────────────────────── Config Comment Management ───────────────────────

    @router.patch(
        "/{token}/comments",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Update config comment",
        description="Update or set comment for a specific config in this subscription",
    )
    async def update_config_comment(
        token: str,
        data: SourceUpdateRequest,
        actor: Actor,
        service: SubscriptionServiceDep,
    ) -> None:
        try:
            await service.update_config_comment(
                token=token,
                user_hash=actor.user_hash,
                provider_hash=_provider_hash(actor),
                config_hash=data.config_id,
                comment=data.comment or settings.domain,
            )
        except Exception as e:
            raise to_http_exception(e) from e

    @router.patch(
        "/{token}/config",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Update config",
        description="Update specific config in this subscription",
    )
    async def update_config(
        token: str,
        data: SourceUpdateRequest,
        actor: Actor,
        service: SubscriptionServiceDep,
    ) -> None:
        try:
            await service.update_config(
                token=token,
                user_hash=actor.user_hash,
                provider_hash=_provider_hash(actor),
                config_hash=data.config_id,
                comment=data.comment,
                is_hidden=data.is_hidden,
                max_depth=data.max_depth,
            )
        except Exception as e:
            raise to_http_exception(e) from e

    # ─────────────────────── Refresh ───────────────────────

    @router.post(
        "/{token}/refresh",
        response_model=RefreshSubscriptionResponse,
        summary="Refresh subscription",
        description="Manually refresh all external URLs in this subscription",
    )
    async def refresh_subscription(
        token: str,
        actor: Actor,
        service: SubscriptionServiceDep,
    ) -> RefreshSubscriptionResponse:
        try:
            return await service.refresh_subscription(
                token=token,
                user_hash=actor.user_hash,
                provider_hash=_provider_hash(actor),
            )
        except Exception as e:
            raise to_http_exception(e) from e

    return router


# ═══════════════════════════════════════════════════════════════════════════
# Concrete routers
# ═══════════════════════════════════════════════════════════════════════════

user_router = build_subscriptions_router(
    prefix="/subs",
    actor_dep=get_actor,
    tags=["Subscriptions"],
)

provider_router = build_subscriptions_router(
    prefix="/providers/{user_id}/subs",
    actor_dep=get_provider_actor,
    tags=["Subscriptions (Provider)"],
)
