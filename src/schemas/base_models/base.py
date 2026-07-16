from pydantic import BaseModel, ConfigDict

# ─────────────────────────────────────────────────────────
# Base model
# ─────────────────────────────────────────────────────────
class BaseModelConfig(BaseModel):
    """Base model with shared configuration."""

    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True,
        use_enum_values=True,
        str_strip_whitespace=True,
        populate_by_name=True,
    )


