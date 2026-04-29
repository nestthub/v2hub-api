"""
Public API endpoints for accessing resolved subscriptions.

These endpoints are publicly accessible (no authentication required)
and return resolved subscription configurations.
"""
import base64

from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse

from src.api.dependencies import ResolverServiceDep
from src.core.exceptions import to_http_exception

router = APIRouter(prefix="/sub", tags=["Public"])


@router.get(
    "/{token}",
    response_class=PlainTextResponse,
    summary="Get resolved subscription",
    description="Get fully resolved subscription as base64-encoded text",
    responses={
        200: {
            "content": {"text/plain": {}},
            "description": "Base64-encoded subscription content",
        }
    },
)
async def get_resolved_subscription_text(
    token: str,
    resolver: ResolverServiceDep,
):
    try:
        result = await resolver.resolve(token)
    
        configs = [item.config for item in result.configs if item.config]
    
        content = "\n".join(configs)
    
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    
        title = base64.b64encode(result.description.encode("utf-8")).decode("ascii")
    
        return Response(
            content=encoded,
            media_type="text/plain",
            headers={
                "profile-title": f"base64:{title}",
                "profile-update-interval": "12",
                "content-disposition": 'attachment; filename="subscription.txt"',
                "cache-control": "no-store",
            }
        )
    
    except Exception as e:
        raise to_http_exception(e)
