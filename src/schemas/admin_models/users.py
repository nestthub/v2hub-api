from pydantic import Field

from .base import AdminBaseModel


class UserCreateRequest(AdminBaseModel):
    """Request model for creating a new user."""
    user_id: int = Field(..., description="External user ID", gt=0)
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": 12345
            }
        }


class UserResponse(AdminBaseModel):
    """Response model for user."""
    user_hash: str = Field(..., description="Generated user hash")
    user_id: int = Field(..., description="User ID")
    api_token: str = Field(..., description="Generated API token")
    is_active: bool = Field(..., description="Account status")
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_hash": "a1b2c3d4e5f6...",
                "user_id": 12345,
                "api_token": "12345:a1b2c3d4e5f6...",
                "is_active": True
            }
        }


class UserStatusUpdateRequest(AdminBaseModel):
    is_active: bool


class UserCreateResponse(UserResponse):
    """Response model for user creation."""
    pass



class TokenRefreshRequest(AdminBaseModel):
    """Request model for refreshing user token."""
    user_id: int = Field(..., description="User ID", gt=0)
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": 12345
            }
        }


class TokenRefreshResponse(AdminBaseModel):
    """Response model for token refresh."""
    user_id: int = Field(..., description="User ID")
    new_api_token: str = Field(..., description="New API token")
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": 12345,
                "new_api_token": "12345_x9y8z7w6v5u4..."
            }
        }
