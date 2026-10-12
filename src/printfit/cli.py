"""printfit command line.

    printfit check <html> [--profile P] [--json] [--out DIR] [--html]
    printfit render <html> [--out DIR]
    printfit preflight <html> [--profile P]
    printfit evaluate [--out eval/results.json]
    printfit fit <html> --profile P --out DIR
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import api
from . import report as REP
from .types import HarnessError


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="printfit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("path"); c.add_argument("--profile"); c.add_argument("--out")
    c.add_argument("--json", action="store_true"); c.add_argument("--html", action="store_true")
    c.add_argument("--diff", help="previous report.json to diff against (default: <out>/report.json "
                                   "from a previous run of the same document, if present)")
    c.add_argument("--no-diff", action="store_true", help="suppress the automatic diff against a previous run")
    c.add_argument("--full", action="store_true", help="print every finding, not just new/changed/regressed")
    c.add_argument("--why", action="store_true", help="print the why: section explaining page overflows")
    r = sub.add_parser("render"); r.add_argument("path"); r.add_argument("--out", default="out/render")
    p = sub.add_parser("preflight"); p.add_argument("path"); p.add_argument("--profile")
    e = sub.add_parser("evaluate"); e.add_argument("--out", default="eval/results.json")
    e.add_argument("--labels", default="eval/labels.yaml"); e.add_argument("--cache", default="eval/cache")
    f = sub.add_parser("fit"); f.add_argument("path"); f.add_argument("--profile"); f.add_argument("--out", required=True)
    f.add_argument("--approach", default="gates"); f.add_argument("--max-iter", type=int, default=4)
    a = ap.parse_args(argv)
    try:
        return {"check": _check, "render": _render, "preflight": _preflight,
                "evaluate": _evaluate, "fit": _fit}[a.cmd](a)
    except HarnessError as ex:
        print(f"harness error: {ex}", file=sys.stderr)
        return 2


def _check(a) -> int:
    out = a.out or os.path.join("out", os.path.splitext(os.path.basename(a.path))[0])
    existing_report = os.path.join(out, "report.json")
    prev_report_path = os.path.join(out, "report.prev.json")
    # Write report.prev.json from the previous run's report.json BEFORE
    # calling api.check, so api.check can compare the fingerprint of this
    # run against the immediately-prior one (task 3).
    existing_js = None
    if os.path.exists(existing_report):
        os.makedirs(out, exist_ok=True)
        with open(existing_report) as fh:
            existing_js = fh.read()
        with open(prev_report_path, "w") as fh:
            fh.write(existing_js)
    rep = api.check(a.path, a.profile, out, no_diff=a.no_diff)
    if rep.verdict == "error":
        print(rep.findings[0].message, file=sys.stderr)
        return 2
    prev_path = a.diff
    prev_js = None
    if prev_path:
        prev_js = REP.load_json(prev_path)
    elif not a.no_diff and existing_js is not None:
        candidate = json.loads(existing_js)
        if os.path.basename(candidate.get("doc") or "") == os.path.basename(a.path):
            prev_js = candidate
    diff = REP.diff_against(prev_js, REP.render_json(rep)) if prev_js else None
    fit_path = os.path.join(out, "fit.json")
    fit_notes = _fit_notes(REP.load_json(fit_path)) if os.path.exists(fit_path) else None
    js = REP.render_json(rep, diff)
    os.makedirs(out, exist_ok=True)
    with open(existing_report, "w") as fh:
        json.dump(js, fh, indent=1)
    if a.path:
        REP.render_html(rep, os.path.join(out, "report.html"))
    if a.json:
        print(json.dumps(js, indent=1))
    else:
        print(REP.render_text(rep, why=a.why, diff=diff, full=a.full, prev=prev_js, fit_notes=fit_notes))
        if diff:
            print("  diff:", {k: len(v) for k, v in diff.items()})
    return 1 if rep.hard_failed else 0


def _fit_notes(fit_js: dict) -> list[str]:
    notes = []
    narrative = fit_js.get("narrative", "")
    for line in narrative.splitlines():
        line = line.strip()
        if "figure knobs skipped" in line:
            notes.append(line if line.startswith("note:") else f"note: {line}")
    core = fit_js.get("core")
    if core:
        notes.append(f"unsatisfiable core: {core}")
    return notes


def _render(a) -> int:
    from .render import render
    art = render(a.path, a.out)
    print(f"{art.page_count} pages -> {a.out}")
    return 0


def _preflight(a) -> int:
    rep = api.preflight_only(a.path, a.profile)
    print(REP.render_text(rep))
    return 1 if rep.hard_failed else 0


def _evaluate(a) -> int:
    from .evaluate import run_eval
    return run_eval(a.labels, a.out, a.cache)


def _fit(a) -> int:
    from .fit import fit
    res = fit(a.path, a.profile, a.out, approach=a.approach, max_iter=a.max_iter)
    print(res.narrative)
    return 0 if res.verdict == "pass" else 1
