"""The fitter: measure once, solve the whole plan with CP-SAT, apply, verify.

Tier 1 of docs/optimisation-loop.md. Knobs are heights the fitter may change
(figure heights per class, answer-space heights per row, an optional page
break before a section heading). Atoms are the unbreakable units of vertical
flow. The height of every atom is affine in the knobs, so page assignment is
an integer feasibility problem: assign atoms to pages in order, keep every
page under budget, honour the profile's page map, minimise page count, then
maximise working room, then move as little as possible.

Content is never changed: structural.compare runs before and after apply and
aborts on any divergence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field

from ortools.sat.python import cp_model

from . import profile as P
from . import render as R
from .approaches import run_approach
from .checks import structural
from .profile import limits_for, role_for
from .report import render_html, render_json
from .types import (PAGE_SLACK_TOLERANCE_PX, TEXT_SCALE_WARN, HarnessError,
                    RenderArtifacts, Report)

TRUST_REGION_PX = 24
DAMPING = 0.7
STYLE_ID = "printfit-fit"


@dataclass
class Knob:
    id: str
    kind: str                     # fig | ws | brk
    current_px: float
    lo: int
    hi: int
    css_selector: str | None = None      # fig: the rule to write
    source_indexes: list[int] = field(default_factory=list)   # ws: inline-style occurrences; brk: h2 index
    convert_from_auto: bool = False
    note: str = ""


@dataclass
class Atom:
    idx: int
    selector: str
    y: float
    h: float
    pitch: float                  # y_next - y, includes the gap below
    coeffs: dict[str, float]      # knob id -> px per px
    break_before: bool
    heading: str | None
    heading_level: int | None
    h2_index: int | None
    group: str | None = None
    fig_floor: float = 0.0        # height kept if every figure shrank to nothing
    rows: list[dict] = field(default_factory=list)   # [{h, cols:[{h, knobs:[(id, cur)]}]}]


@dataclass
class Solution:
    status: str                   # optimal | feasible | infeasible | error
    knobs: dict[str, int]
    pages: list[int]
    page_count: int
    core: list[str] = field(default_factory=list)
    objective: float | None = None


@dataclass
class FitResult:
    doc: str
    verdict: str                  # pass | fail | unsatisfiable | error
    approach: str
    iterations: int
    page_count_before: int
    page_count_after: int
    hard_before: list[str]
    hard_after: list[str]
    knobs_before: dict[str, float]
    knobs_after: dict[str, int]
    narrative: str
    out_dir: str
    core: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------
# knob discovery


def discover_knobs(art: RenderArtifacts, prof: dict, src: str) -> tuple[list[Knob], list[str]]:
    notes: list[str] = []
    knobs: list[Knob] = []
    H = art.page_content_h_px
    body = art.body_font_px
    geom = art.dom_geometry

    # --- figures: one knob per group of same class, viewBox and column width,
    # addressed in the source by a data attribute on the n-th top-level <svg>
    groups: dict[tuple, list[tuple[int, dict]]] = {}
    for n, f in enumerate(geom.get("figures", [])):
        if f["tag"] != "svg" or not f.get("viewbox"):
            continue
        key = (".".join(f["classes"]), int(f["viewbox"]["w"]), int(f["viewbox"]["h"]),
               int(round(f["parent_w"] / 20)))
        groups.setdefault(key, []).append((n, f))
    src_svgs = _svg_occurrences(src)
    n_dom = sum(1 for f in geom.get("figures", []) if f["tag"] == "svg")
    if len(src_svgs) != n_dom:
        notes.append(f"figure knobs skipped: {n_dom} svg figures in the DOM but {len(src_svgs)} in the source")
        groups = {}
    gi = 0
    for key, members in groups.items():
        f0 = members[0][1]
        role = role_for(f0["classes"], f0.get("data_fig_role"), prof)
        lim = limits_for(role, prof)
        label = key[0] or "svg"
        if role in ("scale", "decoration"):
            notes.append(f"fig {label} {key[1]}x{key[2]}: role {role}, height is width-driven; not a knob")
            continue
        hs = [f["rect"]["h"] for _, f in members]
        cur = sum(hs) / len(hs)
        ratios = [t["realised_px"] / body for _, f in members for t in f.get("texts", [])]
        lo_ts = hi_ts = None
        if ratios:
            hi_ts = cur * TEXT_SCALE_WARN[1] / max(ratios)
            lo_ts = cur * TEXT_SCALE_WARN[0] / min(ratios)
        # no width cap: a figure taller than its column allows letterboxes
        # (preserveAspectRatio meet) rather than overflowing
        hi = min(lim.height_frac_max * H, 1.6 * cur, hi_ts or 1e9)
        lo = max(0.6 * 96, lo_ts or 0, 0.4 * cur)
        # a figure that is in band today may stay exactly as it is, even when a
        # ceiling sits a few px below it (border-box rounding); one that is out
        # of band must be moved into it
        in_band = (not ratios or TEXT_SCALE_WARN[0] <= min(ratios) and max(ratios) <= TEXT_SCALE_WARN[1]) \
            and cur <= lim.height_frac_max * H + 2
        if in_band:
            hi, lo = max(hi, cur), min(lo, cur)
        if hi < lo:
            hi = lo
        gi += 1
        knobs.append(Knob(id=f"fig:{gi}:{label}", kind="fig", current_px=cur, lo=int(lo), hi=int(hi),
                          css_selector=f'svg[data-printfit="f{gi}"]',
                          source_indexes=[n for n, _ in members],
                          convert_from_auto=bool(f0["css_height_is_auto"]),
                          note=(f"{len(members)} figure(s) {label} viewBox {key[1]}x{key[2]}, role {role}"
                                + (f", text ratio {min(ratios):.2f}-{max(ratios):.2f}" if ratios else ""))))

    # --- answer space, one knob per row cluster of inline-height boxes -------
    ws_classes = set(prof.get("workspace_classes") or [])
    boxes = geom.get("inline_heights", [])
    src_occ = _inline_height_occurrences(src, set())
    rows: list[tuple[int, float, list[int]]] = []        # (atom idx, y, box indexes)
    if len(src_occ) != len(boxes):
        notes.append(f"answer-space knobs skipped: {len(boxes)} inline-height boxes in the DOM but "
                     f"{len(src_occ)} in the source")
    else:
        for bi, b in enumerate(boxes):
            if ws_classes and not (ws_classes & set(b["classes"])):
                continue
            if not ws_classes and not b["empty"]:
                continue
            if b["atom"] < 0 or b["rect"]["h"] < 24:
                continue
            for r in rows:
                if r[0] == b["atom"] and abs(r[1] - b["rect"]["y"]) < 4:
                    r[2].append(bi)
                    break
            else:
                rows.append((b["atom"], b["rect"]["y"], [bi]))
    for i, y, idxs in rows:
        cur = max(boxes[b]["rect"]["h"] for b in idxs)
        knobs.append(Knob(id=f"ws:{len([x for x in knobs if x.kind == 'ws']) + 1}", kind="ws",
                          current_px=cur, lo=int(max(24, 0.5 * cur)), hi=int(1.75 * cur),
                          source_indexes=idxs, note=f"atom {i}, {len(idxs)} box(es)"))

    # --- optional page breaks before h2 headings ----------------------------
    h2s = _h2_occurrences(src)
    n = 0
    for i, a in enumerate(geom.get("atoms", [])):
        if a.get("heading_level") == 2:
            if not a.get("break_before") and n < len(h2s):
                knobs.append(Knob(id=f"brk:{i}", kind="brk", current_px=0, lo=0, hi=1,
                                  source_indexes=[n], note=a["heading"][:40]))
            n += 1
    return knobs, notes


_INLINE_H = re.compile(r"<(\w+)\b([^>]*?)style=\"([^\"]*?)height\s*:\s*([\d.]+)(in|px|pt|mm)([^\"]*)\"", re.I)


def _inline_height_occurrences(src: str, ws_classes: set[str]) -> list[re.Match]:
    out = []
    for m in _INLINE_H.finditer(src):
        cls = re.search(r"class=\"([^\"]*)\"", m.group(2))
        classes = set(cls.group(1).split()) if cls else set()
        if ws_classes and not (ws_classes & classes):
            continue
        out.append(m)
    return out


def _svg_occurrences(src: str) -> list[re.Match]:
    """Top-level <svg> open tags in source order (nested svgs excluded), which
    is the order the geometry script reports figures."""
    out, depth = [], 0
    for m in re.finditer(r"<svg\b[^>]*>|</svg\s*>", src, re.I):
        if m.group(0).startswith("</"):
            depth = max(0, depth - 1)
        else:
            if depth == 0:
                out.append(m)
            if not m.group(0).rstrip().endswith("/>"):
                depth += 1
    return out


def _h2_occurrences(src: str) -> list[re.Match]:
    return list(re.finditer(r"<h2\b", src, re.I))


# --------------------------------------------------------------------------
# the model


def build_atoms(art: RenderArtifacts, knobs: list[Knob]) -> list[Atom]:
    geom = art.dom_geometry
    raw = sorted(geom.get("atoms", []), key=lambda a: a["rect"]["y"])
    fig_by_sel = {f["selector"]: (n, f) for n, f in enumerate(geom.get("figures", []))}
    knob_of_fig = {n: k.id for k in knobs if k.kind == "fig" for n in k.source_indexes}
    ws_rows = {k.id: k for k in knobs if k.kind == "ws"}
    knob_of_box = {b: k.id for k in knobs if k.kind == "ws" for b in k.source_indexes}
    boxes = geom.get("inline_heights", [])
    atoms: list[Atom] = []
    h2n = 0
    for i, a in enumerate(raw):
        coeffs: dict[str, float] = {}
        in_rows_figs: set[int] = set()
        in_rows_boxes: set[int] = set()
        rows = []
        for r in a.get("rows", []):
            cols = []
            for c in r["cols"]:
                members = []
                for n in c["figs"]:
                    kid = knob_of_fig.get(n)
                    if kid:
                        members.append((kid, geom["figures"][n]["rect"]["h"]))
                    in_rows_figs.add(n)
                for b in c["boxes"]:
                    kid = knob_of_box.get(b)
                    if kid:
                        members.append((kid, boxes[b]["rect"]["h"]))
                    in_rows_boxes.add(b)
                cols.append({"h": c["h"], "knobs": members})
            if any(c["knobs"] for c in cols):
                rows.append({"h": r["h"], "cols": cols})
        # stacked figure knobs: one unit per distinct row of that knob's figures
        stacked: dict[str, set[int]] = {}
        for fsel in a.get("figures", []):
            hit = fig_by_sel.get(fsel)
            if not hit:
                continue
            n, f = hit
            kid = knob_of_fig.get(n)
            if kid and n not in in_rows_figs:
                stacked.setdefault(kid, set()).add(int(round(f["rect"]["y"] / 4)))
        for kid, ys in stacked.items():
            coeffs[kid] = float(len(ys))
        for k in ws_rows.values():
            if k.note.startswith(f"atom {i},") and not all(b in in_rows_boxes for b in k.source_indexes):
                coeffs[k.id] = 1.0
        y = a["rect"]["y"]
        h = a["rect"]["h"]
        pitch = (raw[i + 1]["rect"]["y"] - y) if i + 1 < len(raw) else h
        pitch = max(pitch, h * 0.5) if pitch < h else pitch      # overlapping/absolute quirks
        h2_index = None
        if a.get("heading_level") == 2:
            h2_index = h2n
            h2n += 1
        atoms.append(Atom(idx=i, selector=a["selector"], y=y, h=h, pitch=pitch, coeffs=coeffs,
                          break_before=bool(a.get("break_before")), heading=a.get("heading"),
                          heading_level=a.get("heading_level"), h2_index=h2_index,
                          group=a.get("group"), fig_floor=float(a.get("fig_floor", 0.0)),
                          rows=rows))
    return atoms


def solve(atoms: list[Atom], knobs: list[Knob], H: float, prof: dict,
          max_pages: int, prev: dict[str, int] | None = None,
          trust_px: int | None = None, time_limit: float = 15.0,
          margin_px: float = 0.0, keep_pages: int | None = None,
          notes: list[str] | None = None) -> Solution:
    """keep_pages: when set (a document that already passes and declares no
    page target) the page count is held at that value instead of minimised."""
    m = cp_model.CpModel()
    budget = int(H - PAGE_SLACK_TOLERANCE_PX - margin_px)
    kv: dict[str, cp_model.IntVar] = {}
    bounds: dict[str, tuple[int, int]] = {}
    assumptions: dict[str, cp_model.IntVar] = {}

    def assume(name: str) -> cp_model.IntVar:
        if name not in assumptions:
            assumptions[name] = m.NewBoolVar("a_" + name)
        return assumptions[name]

    for k in knobs:
        lo, hi = k.lo, k.hi
        if prev is not None and trust_px is not None and k.kind != "brk" and k.id in prev:
            lo, hi = max(lo, prev[k.id] - trust_px), min(hi, prev[k.id] + trust_px)
            if lo > hi:
                lo = hi = max(k.lo, min(k.hi, prev[k.id]))
        kv[k.id] = m.NewIntVar(lo, hi, k.id)
        bounds[k.id] = (lo, hi)

    n, Pn = len(atoms), max_pages
    x = [[m.NewBoolVar(f"x{i}_{p}") for p in range(Pn)] for i in range(n)]
    page = [m.NewIntVar(0, Pn - 1, f"page{i}") for i in range(n)]
    for i in range(n):
        m.AddExactlyOne(x[i])
        m.Add(page[i] == sum(p * x[i][p] for p in range(Pn)))
        if i:
            m.Add(page[i] >= page[i - 1])
            if atoms[i].break_before:
                m.Add(page[i] >= page[i - 1] + 1).OnlyEnforceIf(assume("forced_breaks"))
            brk = f"brk:{atoms[i].idx}"
            if brk in kv:
                m.Add(page[i] >= page[i - 1] + kv[brk])
    m.Add(page[0] == 0)
    # atom heights: rest + sum over side-by-side rows of max(column heights)
    # + the stacked knobs, all affine in the knobs
    hmax = int(H * 2)
    hvar: list[cp_model.IntVar] = []
    for i, a in enumerate(atoms):
        cur_part = sum(c * next(k.current_px for k in knobs if k.id == kid)
                       for kid, c in a.coeffs.items() if kid in kv)
        rest = a.pitch - sum(r["h"] for r in a.rows) - cur_part
        expr = [int(round(rest))]
        expr += [int(round(c)) * kv[kid] for kid, c in a.coeffs.items() if kid in kv]
        for ri, r in enumerate(a.rows):
            colvars = []
            for ci, c in enumerate(r["cols"]):
                cv = m.NewIntVar(0, hmax, f"col{i}_{ri}_{ci}")
                base = c["h"] - sum(cur for kid, cur in c["knobs"] if kid in kv)
                m.Add(cv == int(round(base)) + sum(kv[kid] for kid, cur in c["knobs"] if kid in kv))
                colvars.append(cv)
            rv = m.NewIntVar(0, hmax, f"row{i}_{ri}")
            m.AddMaxEquality(rv, colvars)
            expr.append(rv)
        h = m.NewIntVar(0, hmax, f"h{i}")
        m.Add(h == sum(expr))
        hvar.append(h)
    # members of a keep-together group share a page and fit on it together;
    # a forced break inside the group starts a new run
    groups: dict[str, list[int]] = {}
    run_no: dict[str, int] = {}
    for i, a in enumerate(atoms):
        if a.group:
            if a.break_before or a.group not in run_no:
                run_no[a.group] = run_no.get(a.group, -1) + 1
            groups.setdefault(f"{a.group}#{run_no[a.group]}", []).append(i)
    for gname, members in groups.items():
        # a group that cannot fit on a page even with every knob at its floor is
        # one Chrome will break inside anyway: leave it to flow
        floor_total = 0.0
        for i in members:
            a = atoms[i]
            cur_of = lambda kid: next(k.current_px for k in knobs if k.id == kid)
            floor_total += a.pitch - sum(r["h"] for r in a.rows)
            floor_total += sum(c * (bounds[kid][0] - cur_of(kid)) for kid, c in a.coeffs.items() if kid in kv)
            for r in a.rows:
                floor_total += max(c["h"] - sum(cur - bounds[kid][0] for kid, cur in c["knobs"] if kid in kv)
                                   for c in r["cols"])
        if floor_total > budget:
            if notes is not None:
                notes.append(f"{gname.split('#')[0][6:]} cannot fit one page (>= {floor_total:.0f}px); left to flow")
            continue
        for i in members[1:]:
            m.Add(page[i] == page[members[0]])
        m.Add(sum(hvar[i] for i in members) <= budget).OnlyEnforceIf(assume(f"keep_together:{gname[6:].split('#')[0]}"))
    used = [m.NewBoolVar(f"used{p}") for p in range(Pn)]
    for p in range(Pn):
        for i in range(n):
            m.AddImplication(x[i][p], used[p])
        if p:
            m.AddImplication(used[p], used[p - 1])
    # page budgets: sum of h_i over atoms on p, plus slack_p, equals the budget
    slack = [m.NewIntVar(0, budget, f"slack{p}") for p in range(Pn)]
    for p in range(Pn):
        terms = []
        for i in range(n):
            z = m.NewIntVar(0, hmax, f"z{i}_{p}")
            m.Add(z <= hvar[i])
            m.Add(z <= hmax * x[i][p])
            m.Add(z >= hvar[i] - hmax * (1 - x[i][p]))
            terms.append(z)
        m.Add(sum(terms) + slack[p] == budget).OnlyEnforceIf(assume("page_budget"))
    page_count = sum(used)
    if prof.get("pages"):
        m.Add(page_count <= int(prof["pages"])).OnlyEnforceIf(assume("page_cap"))
    for key, want in (prof.get("section_pages") or {}).items():
        for i, a in enumerate(atoms):
            if a.heading and key.lower() in a.heading.lower():
                m.Add(page[i] == int(want) - 1).OnlyEnforceIf(assume(f"section:{key}"))
                break
    # slack counted only on pages that are followed by another used page
    filled = []
    for p in range(Pn - 1):
        w = m.NewIntVar(0, budget, f"w{p}")
        m.Add(w <= slack[p])
        m.Add(w <= budget * used[p + 1])
        m.Add(w >= slack[p] - budget * (1 - used[p + 1]))
        filled.append(w)
    # objective: page count, then unfilled space on non-final pages, then
    # figure stillness (5/px), then answer-space stillness (1/px)
    dev = []
    for k in knobs:
        if k.kind == "brk":
            dev.append(50 * kv[k.id])
            continue
        d = m.NewIntVar(0, 100000, "d" + k.id)
        m.Add(d >= kv[k.id] - int(k.current_px))
        m.Add(d >= int(k.current_px) - kv[k.id])
        dev.append((20 if k.kind == "fig" else 1) * d)
    if keep_pages is not None:
        pdev = m.NewIntVar(0, Pn, "pdev")
        m.Add(pdev >= page_count - keep_pages)
        m.Add(pdev >= keep_pages - page_count)
        page_term = 100000 * pdev
    else:
        page_term = 100000 * page_count
    m.Minimize(page_term + 2 * sum(filled) + sum(dev))
    # hint the current layout so the search starts from something feasible-ish
    for i, a in enumerate(atoms):
        m.AddHint(page[i], min(Pn - 1, int(a.y // H)))
    for k in knobs:
        if k.kind != "brk":
            m.AddHint(kv[k.id], max(bounds[k.id][0], min(bounds[k.id][1], int(k.current_px))))
    m.AddAssumptions(list(assumptions.values()))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    s.parameters.random_seed = 7
    s.parameters.num_workers = 8
    st = s.Solve(m)
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Solution(status="optimal" if st == cp_model.OPTIMAL else "feasible",
                        knobs={k.id: s.Value(kv[k.id]) for k in knobs},
                        pages=[s.Value(page[i]) + 1 for i in range(n)],
                        page_count=int(s.Value(page_count)), objective=s.ObjectiveValue())
    core = []
    if st == cp_model.INFEASIBLE:
        idx = s.SufficientAssumptionsForInfeasibility()
        names = {v.Index(): name for name, v in assumptions.items()}
        core = sorted(names.get(i, str(i)) for i in idx)
    return Solution(status="infeasible" if st == cp_model.INFEASIBLE else "error",
                    knobs={}, pages=[], page_count=0, core=core)


# --------------------------------------------------------------------------
# apply


def apply(src: str, knobs: list[Knob], values: dict[str, int], ws_classes: set[str]) -> str:
    out = src
    # answer-space inline heights, edited from the end so offsets stay valid
    occ = _inline_height_occurrences(out, set())
    edits = []
    for k in knobs:
        if k.kind != "ws" or k.id not in values:
            continue
        for i in k.source_indexes:
            if i < len(occ):
                edits.append((occ[i], values[k.id]))
    for mt, px in sorted(edits, key=lambda e: -e[0].start(4)):
        out = out[:mt.start(4)] + f"{px/96:.3f}" + out[mt.end(4):mt.start(5)] + "in" + out[mt.end(5):]
    # page breaks before h2 headings
    h2s = _h2_occurrences(out)
    marks = sorted((h2s[k.source_indexes[0]] for k in knobs
                    if k.kind == "brk" and values.get(k.id) and k.source_indexes[0] < len(h2s)),
                   key=lambda m: -m.start())
    for mt in marks:
        out = out[:mt.end()] + ' class="printfit-pb"' + out[mt.end():]
    # figures: tag the n-th top-level <svg> with a data attribute, one rule per knob
    svgs = _svg_occurrences(out)
    tags = []
    for gi, k in enumerate((k for k in knobs if k.kind == "fig"), 1):
        if k.id not in values:
            continue
        for n in k.source_indexes:
            if n < len(svgs):
                tags.append((svgs[n], f'f{gi}'))
    for mt, tag in sorted(tags, key=lambda t: -t[0].start()):
        out = out[:mt.start() + 4] + f' data-printfit="{tag}"' + out[mt.start() + 4:]
    rules = [".printfit-pb{break-before:page;page-break-before:always}"]
    for k in knobs:
        if k.kind == "fig" and k.id in values:
            rules.append(f"{k.css_selector}{{height:{values[k.id]/96:.3f}in !important;"
                         "width:auto !important;max-width:100% !important}")
    block = f'<style id="{STYLE_ID}">\n' + "\n".join(rules) + "\n</style>"
    out = re.sub(rf'<style id="{STYLE_ID}">.*?</style>', "", out, flags=re.S)
    i = out.lower().rfind("</style>")
    out = out[:i + 8] + "\n" + block + out[i + 8:] if i >= 0 else block + out
    # a heading given a class must not lose an existing class attribute
    out = re.sub(r'<h2 class="printfit-pb"([^>]*?)class="([^"]*)"', r'<h2\1class="printfit-pb \2"', out)
    return out


# --------------------------------------------------------------------------
# the loop


def fit(html_path: str, profile_path: str | None, out_dir: str, approach: str = "gates",
        max_iter: int = 4, raster_dpi: int = 100) -> FitResult:
    prof = P.load(profile_path)
    ws_classes = set(prof.get("workspace_classes") or [])
    os.makedirs(out_dir, exist_ok=True)
    src0 = open(html_path, encoding="utf-8").read()
    fp0 = structural.fingerprint(html_path)
    before_dir = os.path.join(out_dir, "before")
    art = R.render(html_path, before_dir, raster_dpi=raster_dpi)
    res0 = run_approach(approach, art, prof)
    _write_report(html_path, profile_path, art, res0, before_dir)
    H = art.page_content_h_px
    knobs, notes = discover_knobs(art, prof, src0)
    hist: list[dict] = []
    lines = [f"{os.path.basename(html_path)}: {art.page_count} pages, "
             f"{len(res0.hard_ids)} hard finding(s) under `{approach}` before fitting"]
    lines += [f"  note: {n}" for n in notes]
    lines.append("  knobs: " + (", ".join(f"{k.id}={k.current_px:.0f}px[{k.lo}-{k.hi}]" for k in knobs) or "none"))
    if not knobs:
        result = FitResult(doc=html_path, verdict=res0.verdict, approach=approach, iterations=0,
                           page_count_before=art.page_count, page_count_after=art.page_count,
                           hard_before=res0.hard_ids, hard_after=res0.hard_ids, knobs_before={},
                           knobs_after={}, narrative="\n".join(lines + ["  nothing to fit: no knobs"]),
                           out_dir=out_dir)
        with open(os.path.join(out_dir, "fit.json"), "w") as fh:
            json.dump(asdict(result), fh, indent=1)
        return result
    src = src0
    fitted = os.path.join(out_dir, "fitted.html")
    prev_vals: dict[str, int] | None = None
    seen: set[str] = set()
    cur_art, cur_res = art, res0
    final_verdict = "fail"
    core: list[str] = []
    margin = 0.0
    keep_pages = art.page_count if (res0.verdict == "pass" and not prof.get("pages")) else None
    if keep_pages:
        lines.append(f"  document already passes: holding {keep_pages} pages, filling them, moving as little as possible")
    for it in range(1, max_iter + 1):
        atoms = build_atoms(cur_art, knobs)
        max_pages = max(cur_art.page_count, int(prof.get("pages") or 0)) + 1
        snotes: list[str] = []
        sol = solve(atoms, knobs, H, prof, max_pages, prev=prev_vals,
                    trust_px=TRUST_REGION_PX if prev_vals else None, margin_px=margin,
                    keep_pages=keep_pages, notes=snotes)
        if sol.status == "infeasible" and prev_vals:
            lines.append(f"  iter {it}: infeasible inside the trust region; re-solving freely")
            sol = solve(atoms, knobs, H, prof, max_pages, margin_px=margin, keep_pages=keep_pages)
        if it == 1:
            lines += [f"  note: {n}" for n in snotes]
        if sol.status in ("infeasible", "error"):
            core = sol.core
            lines.append(f"  iter {it}: solver {sol.status}; unsatisfiable core: {core or 'unknown'}")
            final_verdict = "unsatisfiable"
            break
        vals = dict(sol.knobs)
        if prev_vals:                                  # damped correction
            for kid, v in vals.items():
                if kid in prev_vals and not kid.startswith("brk:"):
                    vals[kid] = int(round(prev_vals[kid] + DAMPING * (v - prev_vals[kid])))
        state = hashlib.sha1(json.dumps({k: (v // 2) * 2 for k, v in vals.items()}, sort_keys=True).encode()).hexdigest()
        if state in seen:
            lines.append(f"  iter {it}: cycle detected (knob vector revisited); stopping")
            if cur_res.hard_ids:
                lines.append(f"  residual findings the fitter cannot resize away: {cur_res.hard_ids}")
            final_verdict = "pass" if not cur_res.hard_ids else "fail"
            break
        seen.add(state)
        new_src = apply(src0, knobs, vals, ws_classes)
        with open(fitted, "w", encoding="utf-8") as fh:
            fh.write(new_src)
        bad = structural.compare(fp0, structural.fingerprint(fitted))
        if bad:
            lines.append(f"  iter {it}: structural invariant violated by apply ({[b.id for b in bad]}); aborting")
            final_verdict = "error"
            break
        cur_art = R.render(fitted, out_dir, raster_dpi=raster_dpi)
        cur_res = run_approach(approach, cur_art, prof)
        changed = {k: v for k, v in vals.items() if abs(v - (prev_vals or {k: next(x.current_px for x in knobs if x.id == k)})[k]) >= 1}
        lines.append(f"  iter {it} (margin {margin:.0f}px): solver predicted {sol.page_count} page(s); measured {cur_art.page_count}; "
                     f"{len(cur_res.hard_ids)} hard finding(s); "
                     + (", ".join(f"{k}->{v}" for k, v in sorted(changed.items())) or "no knob change"))
        hist.append({"iter": it, "predicted_pages": sol.page_count, "measured_pages": cur_art.page_count,
                     "hard": cur_res.hard_ids, "knobs": vals,
                     "slack": [round(p.slack_px) for p in cur_art.pages]})
        prev_vals = vals
        if cur_art.page_count > sol.page_count:
            margin += 16.0                     # the model was optimistic: widen the safety margin
        page_ok = (not prof.get("pages")) or cur_art.page_count <= int(prof["pages"])
        residual = [h for h in cur_res.hard_ids if not h.startswith(("page_slack", "qa_overflow", "figure_overflow", "page_count", "section_page", "raster_", "self_sufficiency", "group_proximity", "macro_micro"))]
        layout_bad = [h for h in cur_res.hard_ids if h not in residual]
        if page_ok and not layout_bad and (cur_art.page_count <= sol.page_count or keep_pages):
            final_verdict = "pass" if not cur_res.hard_ids else "fail"
            if residual:
                lines.append(f"  residual findings the fitter cannot resize away: {residual}")
            break
        if not changed and it > 1:
            lines.append(f"  iter {it}: no knob change; stopping")
            if cur_res.hard_ids:
                lines.append(f"  residual findings the fitter cannot resize away: {cur_res.hard_ids}")
            final_verdict = "pass" if not cur_res.hard_ids else "fail"
            break
    _write_report(fitted if hist else html_path, profile_path, cur_art, cur_res, out_dir)
    result = FitResult(doc=html_path, verdict=final_verdict, approach=approach, iterations=len(hist),
                       page_count_before=art.page_count, page_count_after=cur_art.page_count,
                       hard_before=res0.hard_ids, hard_after=cur_res.hard_ids,
                       knobs_before={k.id: round(k.current_px) for k in knobs},
                       knobs_after=prev_vals or {}, narrative="\n".join(lines), out_dir=out_dir,
                       core=core, history=hist)
    with open(os.path.join(out_dir, "fit.json"), "w") as fh:
        json.dump(asdict(result), fh, indent=1)
    return result


def _write_report(doc: str, profile_path: str | None, art: RenderArtifacts, res, out_dir: str) -> None:
    rep = Report(doc=doc, profile=profile_path, verdict=res.verdict, findings=res.findings, artifacts=art)
    with open(os.path.join(out_dir, "report.json"), "w") as fh:
        json.dump(render_json(rep), fh, indent=1)
    render_html(rep, os.path.join(out_dir, "report.html"))
