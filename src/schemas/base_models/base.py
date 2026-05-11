from pydantic import BaseModel, ConfigDict

# ─────────────────────────────────────────────────────────
# Utils
# ─────────────────────────────────────────────────────────

def _clean_sources(items: list[str]) -> list[str]:
    cleaned, seen = [], set()
    for item in items:
        v = item.strip()
        if v and v not in seen:
            seen.add(v)
            cleaned.append(v)
    return cleaned


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


