"""Fonts. Hard when a declared family failed `document.fonts.check()`; this is
what stops a CI Linux box silently substituting Liberation Sans and
false-failing every golden."""
from __future__ import annotations

from ..types import Finding, RenderArtifacts


def run(artifacts: RenderArtifacts, profile: dict) -> list[Finding]:
    required = (profile.get("fonts") or {}).get("required")
    missing = [f for f in artifacts.fonts_missing if not required or f in required]
    return [Finding(id=f"fonts:{f}", severity="hard",
                    message=f"declared font family '{f}' is not available to Chrome; "
                            "the render used a substitute")
            for f in missing]
