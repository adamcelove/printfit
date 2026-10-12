"""Profile loading. A profile DECLARES figure roles and per-document limits;
it never infers them. Unknown keys are errors."""
from __future__ import annotations

import dataclasses

import yaml

from .types import ROLE_LIMITS, FigRole, ProfileError, RoleLimits

ALLOWED_KEYS = {"schema", "name", "documents", "roles", "role_limits",
                "text_scale_exempt", "fill", "fonts", "golden", "pages",
                "section_pages", "workspace_classes", "knobs", "composition"}
_VALID_ROLES = set(FigRole.__args__)


def load(path: str | None) -> dict:
    if path is None:
        return {"roles": {}, "role_limits": {}, "text_scale_exempt": [],
                "fill": {"enabled": True, "skip_final_page": True,
                         "skip_explicit_break_pages": True},
                "fonts": {}, "documents": []}
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    unknown = set(data) - ALLOWED_KEYS
    if unknown:
        raise ProfileError(f"{path}: unknown top-level keys {sorted(unknown)}")
    for cls, role in (data.get("roles") or {}).items():
        if role not in _VALID_ROLES:
            raise ProfileError(f"{path}: roles.{cls}: unknown role {role!r}")
    for role, over in (data.get("role_limits") or {}).items():
        if role not in _VALID_ROLES:
            raise ProfileError(f"{path}: role_limits.{role}: unknown role")
        bad = set(over) - {f.name for f in dataclasses.fields(RoleLimits)}
        if bad:
            raise ProfileError(f"{path}: role_limits.{role}: unknown fields {sorted(bad)}")
    base = load(None)
    base.update(data)
    base["fill"] = {**load(None)["fill"], **(data.get("fill") or {})}
    base["roles"] = data.get("roles") or {}
    base["role_limits"] = data.get("role_limits") or {}
    base["text_scale_exempt"] = data.get("text_scale_exempt") or []
    return base


def role_for(el_classes: list[str], data_role: str | None, profile: dict) -> FigRole:
    """attribute > profile map > unknown."""
    if data_role in _VALID_ROLES:
        return data_role  # type: ignore[return-value]
    roles = profile.get("roles") or {}
    # most specific class wins: the last class listed in the profile that the
    # element carries (g-nl over grid when both are mapped)
    hit = "unknown"
    for cls in el_classes:
        if cls in roles:
            hit = roles[cls]
    return hit  # type: ignore[return-value]


def limits_for(role: FigRole, profile: dict) -> RoleLimits:
    base = ROLE_LIMITS[role]
    over = (profile.get("role_limits") or {}).get(role) or {}
    return dataclasses.replace(base, **over) if over else base
