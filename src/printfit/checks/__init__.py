"""Check registry. Every measured check has the signature
    run(artifacts: RenderArtifacts, profile: dict) -> list[Finding]
and reads only the artifacts; no check launches a browser."""
from __future__ import annotations

from ..types import HARD_GATES, Finding, RenderArtifacts  # noqa: F401


def run_all(artifacts: RenderArtifacts, profile: dict
            ) -> tuple[list[Finding], list[str]]:
    """Run every measured check. Returns (findings, skipped_checks)."""
    from . import arrow_shaft, aspect_ratio, figure_height, fonts, label_collision, page_slack, text_scale
    findings: list[Finding] = []
    skipped: list[str] = []
    for mod in (text_scale, figure_height, aspect_ratio, page_slack, fonts,
                label_collision, arrow_shaft):
        findings.extend(mod.run(artifacts, profile))
    roles = profile.get("roles") or {}
    has_declared = bool(roles) or any(
        f.get("data_fig_role") for f in artifacts.dom_geometry.get("figures", []))
    if artifacts.dom_geometry.get("figures") and not has_declared:
        skipped += ["aspect_ratio", "auto_height"]
    return findings, skipped
