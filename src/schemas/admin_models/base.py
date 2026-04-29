from pydantic import BaseModel, ConfigDict


class AdminBaseModel(BaseModel):
    """Base model for admin endpoints."""

    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True,
        str_strip_whitespace=True,
        populate_by_name=True,
    )
