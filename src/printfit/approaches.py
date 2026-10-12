"""The three competing judgements of "does this page look good", behind one
signature so the evaluator and the fitter can swap them.

  gates    deterministic DOM+PDF checks (checks/*)          -- approach A
  raster   pixel-only features over the page PNGs (features) -- approach B
  spacing  DOM-geometry composition checks (checks/spacing)  -- approach C
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .types import Finding, RenderArtifacts

APPROACHES = ("gates", "raster", "spacing")


@dataclass
class ApproachResult:
    name: str
    verdict: str                      # pass | fail
    findings: list[Finding] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def hard_ids(self) -> list[str]:
        return sorted(f.id for f in self.findings if f.failed)

    @property
    def hard_checks(self) -> set[str]:
        return {f.id.split(":")[0] for f in self.findings if f.failed}


def run_approach(name: str, artifacts: RenderArtifacts, profile: dict,
                 golden_dir: str | None = None) -> ApproachResult:
    t = time.perf_counter()
    if name == "gates":
        from .checks import run_all
        findings, _ = run_all(artifacts, profile)
        verdict = "fail" if any(f.failed for f in findings) else "pass"
    elif name == "raster":
        from .features import verdict as raster_verdict
        verdict, findings = raster_verdict(artifacts, profile, golden_dir)
    elif name == "spacing":
        from .checks.spacing import verdict as spacing_verdict
        verdict, findings = spacing_verdict(artifacts, profile)
    else:
        raise ValueError(f"unknown approach {name!r}; choose from {APPROACHES}")
    return ApproachResult(name=name, verdict=verdict, findings=list(findings),
                          seconds=time.perf_counter() - t)
