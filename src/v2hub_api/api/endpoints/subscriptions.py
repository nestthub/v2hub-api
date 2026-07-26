"""
Subscription management API endpoints.

Provides REST API for:
- Creating subscriptions
- Listing user's subscriptions
- Getting subscription details
- Updating subscription metadata
- Deleting subscriptions
- Managing sources (add, replace, remove)
- Managing config comments
"""

from fastapi import APIRouter, status

from v2hub_api.api.dependencies import CurrentUser, ResolverServiceDep, SubscriptionServiceDep
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

router = APIRouter(prefix="/subs", tags=["Subscriptions"])


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

    # Создаем словарь комментариев для быстрого доступа
    comment_map = {cc.config_hash: cc.comment for cc in subscription.config_comments}

    for source in subscription.sources:
        # Формируем поле data в зависимости от типа источника
        if source.source_type == SourceType.CONFIG.value and source.config_hash:
            # Для CONFIG берем config_data из proxy_config
            config_data = source.proxy_config.config_data if source.proxy_config else ""

            # Добавляем комментарий если есть
            comment = comment_map.get(source.config_hash)
            data = f"{config_data}#{comment}" if comment else config_data
        elif source.source_type == SourceType.INTERNAL_TOKEN.value and source.internal_token:
            data = f"https://{settings.domain}/sub/{source.internal_token}"

        elif source.source_type == SourceType.EXTERNAL_URL and source.external_url:
            # Для EXTERNAL_URL просто берем external_url
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


# ═══════════════════════════════════════════════════════════════════════════
# Subscription CRUD
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create subscription",
    description="Create a new subscription with optional initial sources",
)
async def create_subscription(
    data: SubscriptionCreateRequest,
    current_user: CurrentUser,
    service: SubscriptionServiceDep,
    resolver: ResolverServiceDep,
) -> SubscriptionResponse:
    """
    Create a new subscription.

    - **name**: Unique name for this subscription (per user)
    - **description**: Optional description
    - **sources**: Optional list of initial sources

    Sources can be:
    - Proxy configs (vless://, vmess://, trojan://, ss://, etc.)
    - External subscription URLs (https://...)
    - Internal references (another subscription token)
    """
    try:
        subscription = await service.create_subscription(
            user_hash=current_user.user_hash,
            name=data.name,
            description=data.description,
            sources=data.sources,
        )

        # Подсчитываем реальное количество конфигов
        sources_count = await get_total_configs_count(subscription.token, resolver)

        return SubscriptionResponse(
            token=subscription.token,
            name=subscription.name,
            description=subscription.description,
            sources=convert_sources_to_out(subscription),
            sources_count=sources_count,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
        )

    except Exception as e:
        raise to_http_exception(e) from e


@router.get(
    "",
    response_model=list[SubscriptionListItem],
    summary="List subscriptions",
    description="List all subscriptions for the authenticated user",
)
async def list_subscriptions(
    current_user: CurrentUser,
    service: SubscriptionServiceDep,
    resolver: ResolverServiceDep,
) -> list[SubscriptionListItem]:
    """
    Get list of all subscriptions owned by the current user.

    Returns summary information without full source details.
    """
    try:
        subscriptions = await service.list_subscriptions(user_hash=current_user.user_hash)

        result = []
        for subscription in subscriptions:
            # Подсчитываем реальное количество конфигов для каждой подписки
            sources_count = await get_total_configs_count(subscription.token, resolver)

            result.append(
                SubscriptionListItem(
                    token=subscription.token,
                    name=subscription.name,
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
    current_user: CurrentUser,
    service: SubscriptionServiceDep,
    resolver: ResolverServiceDep,
) -> SubscriptionResponse:
    """
    Get detailed information about a specific subscription.

    Includes all sources with their configurations.
    """
    try:
        subscription = await service.get_subscription(
            token=token,
            user_hash=current_user.user_hash,
        )

        # Подсчитываем реальное количество конфигов
        sources_count = await get_total_configs_count(subscription.token, resolver)

        return SubscriptionResponse(
            token=subscription.token,
            name=subscription.name,
            description=subscription.description,
            sources=convert_sources_to_out(subscription),
            sources_count=sources_count,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
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
    current_user: CurrentUser,
    service: SubscriptionServiceDep,
    resolver: ResolverServiceDep,
) -> SubscriptionResponse:
    """
    Update subscription metadata.

    - **name**: New name (must be unique per user)
    - **description**: New description
    """
    try:
        subscription = await service.update_subscription(
            token=token,
            user_hash=current_user.user_hash,
            name=data.name,
            description=data.description,
        )

        # Подсчитываем реальное количество конфигов
        sources_count = await get_total_configs_count(subscription.token, resolver)

        return SubscriptionResponse(
            token=subscription.token,
            name=subscription.name,
            description=subscription.description,
            sources=convert_sources_to_out(subscription),
            sources_count=sources_count,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
        )

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
    current_user: CurrentUser,
    service: SubscriptionServiceDep,
) -> None:
    """
    Permanently delete a subscription.

    This will also delete all associated sources and comments.
    """
    try:
        await service.delete_subscription(
            token=token,
            user_hash=current_user.user_hash,
        )

    except Exception as e:
        raise to_http_exception(e) from e


# ═══════════════════════════════════════════════════════════════════════════
# Source Management
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/{token}/sources",
    response_model=SubscriptionResponse,
    summary="Add sources",
    description="Add new sources to a subscription",
)
async def add_sources(
    token: str,
    data: SourcesAddRequest,
    current_user: CurrentUser,
    service: SubscriptionServiceDep,
    resolver: ResolverServiceDep,
) -> SubscriptionResponse:
    """
    Add new sources to an existing subscription.

    Duplicates are automatically filtered out.
    Sources can include comments using the # syntax:
    - vless://uuid@server:port#MyServer
    """
    try:
        subscription = await service.add_sources(
            token=token,
            user_hash=current_user.user_hash,
            sources=data.sources,
        )

        # Подсчитываем реальное количество конфигов
        sources_count = await get_total_configs_count(subscription.token, resolver)

        return SubscriptionResponse(
            token=subscription.token,
            name=subscription.name,
            description=subscription.description,
            sources=convert_sources_to_out(subscription),
            sources_count=sources_count,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
        )

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
    current_user: CurrentUser,
    service: SubscriptionServiceDep,
    resolver: ResolverServiceDep,
) -> SubscriptionResponse:
    """
    Replace all sources in a subscription.

    This is an atomic operation - all existing sources are deleted
    and new ones are added.
    """
    try:
        subscription = await service.replace_sources(
            token=token,
            user_hash=current_user.user_hash,
            sources=data.sources,
        )

        # Подсчитываем реальное количество конфигов
        sources_count = await get_total_configs_count(subscription.token, resolver)

        return SubscriptionResponse(
            token=subscription.token,
            name=subscription.name,
            description=subscription.description,
            sources=convert_sources_to_out(subscription),
            sources_count=sources_count,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
        )

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
    current_user: CurrentUser,
    service: SubscriptionServiceDep,
    resolver: ResolverServiceDep,
) -> SubscriptionResponse:
    """
    Remove specific sources from a subscription.

    Provide the source IDs to remove.
    """
    try:
        subscription = await service.remove_sources(
            token=token,
            user_hash=current_user.user_hash,
            source_ids=data.source_ids,
        )

        # Подсчитываем реальное количество конфигов
        sources_count = await get_total_configs_count(subscription.token, resolver)

        return SubscriptionResponse(
            token=subscription.token,
            name=subscription.name,
            description=subscription.description,
            sources=convert_sources_to_out(subscription),
            sources_count=sources_count,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
        )

    except Exception as e:
        raise to_http_exception(e) from e


# ═══════════════════════════════════════════════════════════════════════════
# Config Comment Management
# ═══════════════════════════════════════════════════════════════════════════


@router.patch(
    "/{token}/comments",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Update config comment",
    description="Update or set comment for a specific config in this subscription",
)
async def update_config_comment(
    token: str,
    data: SourceUpdateRequest,
    current_user: CurrentUser,
    service: SubscriptionServiceDep,
) -> None:
    """
    Update the comment for a specific config within this subscription.

    This allows the same proxy config to have different comments
    in different subscriptions.

    - **config_hash**: Hash of the config to comment
    - **comment**: Comment text (without # prefix)
    """
    try:
        await service.update_config_comment(
            token=token,
            user_hash=current_user.user_hash,
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
    current_user: CurrentUser,
    service: SubscriptionServiceDep,
) -> None:
    """
    Update settings for a specific config within this subscription.

    Allows partial updates of a config source. Only the fields provided
    in the request will be modified.

    Supported fields:
    - **config_id**: Hash of the config to update
    - **comment**: Config comment text (without # prefix)
    - **is_hidden**: Whether the config is hidden from end users
    - **max_depth**: Maximum nesting depth for config visibility propagation
    """
    try:
        await service.update_config(
            token=token,
            user_hash=current_user.user_hash,
            config_hash=data.config_id,
            comment=data.comment,
            is_hidden=data.is_hidden,
            max_depth=data.max_depth,
        )

    except Exception as e:
        raise to_http_exception(e) from e


# ═══════════════════════════════════════════════════════════════════════════
# Subscription Refresh Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/{token}/refresh",
    response_model=RefreshSubscriptionResponse,
    summary="Refresh subscription",
    description="Manually refresh all external URLs in this subscription",
)
async def refresh_subscription(
    token: str,
    current_user: CurrentUser,
    service: SubscriptionServiceDep,
) -> RefreshSubscriptionResponse:
    """
    Manually trigger refresh of all external URL sources in this subscription.

    This fetches fresh content from external URLs and updates the cache.
    Does NOT affect CONFIG or INTERNAL_TOKEN sources.

    Normally, external URLs are refreshed automatically every 15 minutes
    by a background task. Use this endpoint to force an immediate refresh.

    Returns statistics about the refresh operation.
    """
    try:
        result = await service.refresh_subscription(
            token=token,
            user_hash=current_user.user_hash,
        )
        return result

    except Exception as e:
        raise to_http_exception(e) from e
