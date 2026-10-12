"""The one function the CLI, the evaluator and the fitter share."""
from __future__ import annotations

import json
import os
import tempfile

from . import profile as P
from . import render as R
from . import report as REP
from .checks import run_all, structural
from .checks.color import preflight_print_color
from .checks.text_scale import preflight
from .types import Finding, HarnessError, RenderArtifacts, Report


def check(html_path: str, profile_path: str | None = None, out_dir: str | None = None,
          artifacts: RenderArtifacts | None = None, raster_dpi: int = 150,
          no_diff: bool = False) -> Report:
    prof = P.load(profile_path)
    out_dir = out_dir or tempfile.mkdtemp(prefix="printfit-")
    try:
        art = artifacts or R.render(html_path, out_dir, raster_dpi=raster_dpi)
    except HarnessError as e:
        return Report(doc=html_path, profile=profile_path, verdict="error",
                      findings=[Finding(id="harness", severity="hard", message=str(e))],
                      artifacts=None)
    findings, skipped = run_all(art, prof)
    findings += preflight(html_path, prof)
    findings += preflight_print_color(html_path)
    fp = structural.fingerprint(html_path)
    prev_path = os.path.join(out_dir, "report.prev.json")
    if not no_diff and os.path.exists(prev_path):
        with open(prev_path, encoding="utf-8") as fh:
            prev_js = json.load(fh)
        # same-document guard: never diff a fingerprint against a previous
        # run of a DIFFERENT document that happened to share this out dir --
        # the same guard the finding diff applies in cli.py.
        same_doc = os.path.basename(prev_js.get("doc") or "") == os.path.basename(html_path)
        prev_fp = prev_js.get("fingerprint")
        if same_doc and prev_fp:
            findings += structural.compare(prev_fp, fp)
    verdict = "fail" if any(f.failed for f in findings) else "pass"
    rep = Report(doc=html_path, profile=profile_path, verdict=verdict,
                 findings=findings, artifacts=art, skipped_checks=skipped)
    rep.why = REP.compute_why(art, findings)
    rep.fingerprint = fp
    return rep


def preflight_only(html_path: str, profile_path: str | None = None) -> Report:
    prof = P.load(profile_path)
    findings = preflight(html_path, prof) + preflight_print_color(html_path)
    fp = structural.fingerprint(html_path)
    findings.append(Finding(id="structural:fingerprint", severity="info",
                            message=f"h1 {fp['h1']}, h2 {fp['h2']}, svg {fp['svg']}, qa {fp['qa']}, "
                                    f"text {fp['text_len']} chars"))
    return Report(doc=html_path, profile=profile_path,
                  verdict="fail" if any(f.failed for f in findings) else "pass",
                  findings=findings, artifacts=None)
