"""Report rendering. The only module that formats findings for humans.

The report must show per-page fill and slack, every finding with its measured
value against its threshold, and -- when the document cannot be fitted --
which constraint could not be satisfied. A report that says only "failed" puts
the human back to guessing, which is the situation the harness exists to end.
"""
from __future__ import annotations

import dataclasses
import json
import os

from PIL import Image, ImageDraw

from . import __version__
from .types import PAGE_SLACK_TOLERANCE_PX, Finding, RenderArtifacts, Report

ORDER = {"hard": 0, "soft": 1, "info": 2}


def render_text(report: Report, why: bool = False, diff: dict | None = None, full: bool = False,
                prev: dict | None = None, fit_notes: list[str] | None = None) -> str:
    lines = []
    art = report.artifacts
    if art:
        for p in art.pages:
            flag = next((f for f in report.findings if f.id == f"page_slack:page-{p.index}" and f.failed), None)
            tail = f"FAIL slack < {flag.threshold:.0f}px" if flag else "OK"
            note = "  (final)" if p.is_final else ("  (break)" if p.ends_in_explicit_break else "")
            lines.append(f"  page {p.index:<2} fill {p.fill_ratio:4.0%}   slack {p.slack_px:5.0f}px   {tail}{note}")
        lines.append("")
    if why:
        lines.extend(render_why_text(report.why or [], fit_notes))
    shown = sorted((f for f in report.findings if f.severity != "info"),
                   key=lambda f: (ORDER[f.severity], f.id))
    hard = [f for f in shown if f.severity == "hard"]
    prev_by_id = {f["id"]: f for f in (prev or {}).get("findings", [])}
    if diff is not None and not full:
        interesting = set(diff.get("new", [])) | set(diff.get("regressed", [])) | set(diff.get("changed", []))
        soft_info = [f for f in shown if f.severity != "hard"]
        to_print = hard + [f for f in soft_info if f.id in interesting]
        seen = set()
        for f in to_print:
            if f.id in seen:
                continue
            seen.add(f.id)
            lines.extend(_finding_lines(f, diff, prev_by_id))
        if diff.get("fixed"):
            lines.append(f"  fixed: {', '.join(diff['fixed'])}")
        hidden_soft = sum(1 for f in soft_info if f.id not in interesting and f.severity == "soft")
        hidden_info = sum(1 for f in report.findings
                          if f.severity == "info" and f.id not in interesting)
        lines.append(f"  unchanged: {hidden_soft} soft, {hidden_info} info (hidden; --full to show)")
    else:
        for f in shown:
            lines.extend(_finding_lines(f, diff, prev_by_id))
    if report.skipped_checks:
        lines.append(f"\n  skipped (no profile roles): {', '.join(report.skipped_checks)}")
    n = report.hard_failed
    lines.append(f"\n  {n} hard gate{'s' if n != 1 else ''} failed" if n else "\n  all hard gates pass")
    lines.append(f"  verdict: {report.verdict}")
    return "\n".join(lines)


def _finding_lines(f: Finding, diff: dict | None, prev_by_id: dict | None = None) -> list[str]:
    val = f"{f.value:.2f}" if f.value is not None else ""
    thr = f"(limit {f.threshold})" if f.threshold is not None else ""
    changed = diff and f.id in (diff.get("changed", []) + diff.get("regressed", []))
    if changed and prev_by_id and f.id in prev_by_id and prev_by_id[f.id].get("value") is not None:
        was = prev_by_id[f.id]["value"]
        val = f"{was:.2f} → {f.value:.2f}" if f.value is not None else f"{was:.2f} → -"
    out = [f"  {f.severity.upper():<5} {f.id:<40} {val:>6} {thr}"]
    out.append(f"        {f.message}")
    if f.suggested_fix:
        out.append(f"        fix: {f.suggested_fix}")
    return out


def render_why_text(entries: list[dict], fit_notes: list[str] | None = None) -> list[str]:
    lines = ["  why:"]
    if not entries:
        lines.append("    (no page_slack or section_page hard findings)")
    for e in entries:
        if e.get("kind") == "underfull":
            lines.append(f"    {e['message']}")
            if e.get("cause"):
                lines.append(f"      cause: {e['cause']}")
            if e.get("suggestion"):
                lines.append(f"      {e['suggestion']}")
            continue
        lines.append(f"    {e['message']}")
        if e.get("straddling"):
            lines.append(f"      straddling atom: {e['straddling']}")
        else:
            lines.append(f"      {e.get('no_straddle_reason', 'no atom crosses the boundary')}")
        if e.get("preceded_by"):
            lines.append(f"      preceded by: {e['preceded_by']}")
        if e.get("absorb_with"):
            lines.append(f"      absorb with: {' · '.join(e['absorb_with'])}")
    for note in (fit_notes or []):
        lines.append(f"    {note}")
    lines.append("")
    return lines


def render_json(report: Report, diff: dict | None = None) -> dict:
    art = report.artifacts
    return {
        "schema": 1, "printfit": __version__,
        "doc": report.doc, "profile": report.profile,
        "verdict": report.verdict, "hard_failed": report.hard_failed,
        "render": None if art is None else {
            "page_count": art.page_count, "paper_w_px": art.paper_w_px, "paper_h_px": art.paper_h_px,
            "page_content_h_px": art.page_content_h_px, "page_content_w_px": art.page_content_w_px,
            "page_margin_source": art.page_margin_source, "media_emulation": art.media_emulation,
            "body_font_px": art.body_font_px, "raster_dpi": art.raster_dpi,
            "chrome_path": art.chrome_path, "chrome_version": art.chrome_version,
            "fonts_resolved": art.fonts_resolved, "fonts_missing": art.fonts_missing,
            "page_map": art.dom_geometry.get("page_map", {}),
            "pdf_path": art.pdf_path, "page_png_paths": art.page_png_paths},
        "pages": [] if art is None else [dataclasses.asdict(p) for p in art.pages],
        "skipped_checks": list(report.skipped_checks),
        "findings": [dataclasses.asdict(f) for f in
                     sorted(report.findings, key=lambda f: (ORDER[f.severity], f.id))],
        "diff": diff or {"new": [], "fixed": [], "changed": [], "regressed": []},
        "why": report.why or [],
        "fingerprint": report.fingerprint,
    }


def diff_against(prev: dict, cur: dict) -> dict:
    """Classify each finding id as new / fixed / changed / regressed."""
    pf = {f["id"]: f for f in prev.get("findings", []) if f["severity"] != "info"}
    cf = {f["id"]: f for f in cur.get("findings", []) if f["severity"] != "info"}
    out = {"new": [], "fixed": [], "changed": [], "regressed": []}
    for fid in cf:
        if fid not in pf:
            out["new"].append(fid)
    for fid, f in pf.items():
        if fid not in cf:
            out["fixed"].append(fid)
            continue
        c = cf[fid]
        if f["severity"] == "hard" and c["severity"] != "hard":
            out["fixed"].append(fid)
        elif f["severity"] != "hard" and c["severity"] == "hard":
            out["regressed"].append(fid)
        elif f.get("value") != c.get("value"):
            worse = _worse(f, c)
            out["regressed" if worse else "changed"].append(fid)
    return out


def _worse(prev: dict, cur: dict) -> bool:
    t = cur.get("threshold")
    if t is None or prev.get("value") is None or cur.get("value") is None:
        return False
    # same side of the threshold and further from it = worse; crossing the
    # threshold with the finding still present is reported as changed
    if (cur["value"] > t) != (prev["value"] > t):
        return False
    return abs(cur["value"] - t) > abs(prev["value"] - t)


def render_html(report: Report, out_path: str) -> str:
    """Self-contained page: each page PNG with failing elements outlined by a
    numbered red box drawn from their geometry rects."""
    art = report.artifacts
    if art is None:
        html = f"<h1>{report.doc}</h1><p>verdict: {report.verdict}</p>"
        open(out_path, "w").write(html)
        return html
    scale = art.raster_dpi / 96
    H = art.page_content_h_px
    top_margin = _top_margin(art)
    numbered = [f for f in report.findings if f.severity != "info" and f.selector]
    rects = _rects_by_selector(art)
    imgs = []
    outdir = os.path.dirname(os.path.abspath(out_path))
    for i, png in enumerate(art.page_png_paths, 1):
        im = Image.open(png).convert("RGB")
        dr = ImageDraw.Draw(im)
        for n, f in enumerate(numbered, 1):
            r = rects.get(f.selector)
            if not r:
                continue
            page = int(r["y"] // H) + 1
            if page != i:
                continue
            x, y = r["x"] * scale, (r["y"] - (page - 1) * H + top_margin) * scale
            w, h = r["w"] * scale, r["h"] * scale
            col = (220, 30, 30) if f.failed else (230, 140, 0)
            dr.rectangle([x, y, x + w, y + h], outline=col, width=4)
            dr.rectangle([x, y - 26, x + 34, y], fill=col)
            dr.text((x + 6, y - 24), str(n), fill=(255, 255, 255))
        dst = os.path.join(outdir, f"report-page-{i}.png")
        im.save(dst)
        imgs.append(os.path.basename(dst))
    rows = "".join(
        f"<tr><td>{n}</td><td class={f.severity}>{f.severity}</td><td><code>{f.id}</code></td>"
        f"<td>{'' if f.value is None else f.value}</td><td>{'' if f.threshold is None else f.threshold}</td>"
        f"<td>{f.message}<br><i>{f.suggested_fix or ''}</i></td></tr>"
        for n, f in enumerate(numbered, 1))
    pages = "".join(
        f"<figure><img src='{src}' style='width:100%;max-width:560px;border:1px solid #ccc'>"
        f"<figcaption>page {p.index}: fill {p.fill_ratio:.0%}, slack {p.slack_px:.0f}px</figcaption></figure>"
        for src, p in zip(imgs, art.pages))
    html = f"""<!doctype html><meta charset=utf-8><title>printfit report</title>
<style>body{{font:14px system-ui;margin:24px;color:#222}} figure{{display:inline-block;margin:8px;vertical-align:top}}
table{{border-collapse:collapse}} td{{border:1px solid #ddd;padding:4px 8px;vertical-align:top}}
td.hard{{color:#c00;font-weight:600}} td.soft{{color:#b60}}</style>
<h1>{os.path.basename(report.doc)} — {report.verdict} ({report.hard_failed} hard)</h1>
<p>{art.page_count} pages · body {art.body_font_px:.2f}px · content box {art.page_content_w_px:.0f}×{art.page_content_h_px:.0f}px · {art.chrome_version}</p>
<div>{pages}</div>
<table><tr><th>#</th><th>sev</th><th>id</th><th>value</th><th>limit</th><th>message</th></tr>{rows}</table>"""
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return html


def compute_why(art: RenderArtifacts, findings: list[Finding]) -> list[dict]:
    """One entry per hard page_slack or section_page finding.

    page_slack: the atom straddling the page boundary (or, if none crosses,
    why not), the heading before it, and up to three height/figure
    candidates that could absorb the true overflow or slack shortfall.

    section_page: a heading landed on the wrong page because the PAGE BEFORE
    it ended early -- an underfull entry naming the atom that did not fit and
    whether it geometrically should have."""
    if art is None:
        return []
    geom = art.dom_geometry
    atoms = sorted(geom.get("atoms", []), key=lambda a: a["rect"]["y"])
    out = []
    for f in findings:
        if not f.failed:
            continue
        if f.id.startswith("page_slack:page-"):
            page = f.page or int(f.id.rsplit("-", 1)[1])
            if page is None:
                continue
            out.append(_page_slack_entry(art, atoms, page, f, PAGE_SLACK_TOLERANCE_PX))
        elif f.id.startswith("section_page:"):
            landed = f.page
            if not landed or landed <= 1:
                continue
            entry = _underfull_entry(art, atoms, landed - 1)
            if entry:
                out.append(entry)
    # any other page that fills under half, is not final, and does not end in
    # an explicit break is underfull even without a section_page finding to
    # flag it -- the section_page check only fires when a profile declares
    # section_pages, but the mechanism (a keep-together group didn't fit) is
    # the same either way.
    covered = {e["page"] for e in out}
    for p in art.pages:
        if (p.index not in covered and not p.is_final and not p.ends_in_explicit_break
                and p.fill_ratio < 0.5):
            entry = _underfull_entry(art, atoms, p.index)
            if entry:
                out.append(entry)
                covered.add(p.index)
    return out


def _page_of(y: float, H: float) -> int:
    """1-indexed page containing DOM-model y `y`.

    Atom `rect.y` values are unpaginated document-flow coordinates with no
    top-margin offset -- the same convention `checks/page_slack.py` uses in
    `qa_overflow`/`qa_split` (`int(offset_top // H) + 1`) to assign an atom to
    a page from its DOM position. Page N spans y in [(N-1)*H, N*H)."""
    return int(y // H) + 1


def _page_end_y(n: int, H: float) -> float:
    """Absolute DOM-model y at which page n's content box ends (exclusive)."""
    return n * H


def _page_slack_entry(art: RenderArtifacts, atoms: list[dict], page: int, f: Finding,
                      tolerance: float) -> dict:
    H = art.page_content_h_px
    boundary_y = _page_end_y(page, H)
    value = f.value
    threshold = f.threshold if f.threshold is not None else tolerance
    over_px = None
    short_by_px = None
    if value is not None and value < 0:
        over_px = -value
        headline = f"page {page} overflows by {over_px:.0f}px"
    elif value is not None and value < threshold:
        short_by_px = threshold - value
        headline = f"page {page} is {short_by_px:.0f}px short of the {threshold:.0f}px slack floor"
    else:
        headline = f"page {page} slack {value:.0f}px" if value is not None else f"page {page} fails page_slack"
    # same reduction target as the page_slack finding's own suggested_fix:
    # tolerance - slack + tolerance (a 12px cushion beyond the floor)
    reduction_target = (tolerance - value + tolerance) if value is not None else 0.0
    kind = "overflow" if over_px is not None else "short"
    entry = {"kind": kind, "page": page, "message": headline,
             "over_px": over_px, "short_by_px": short_by_px,
             "straddling": None, "no_straddle_reason": None,
             "preceded_by": None, "absorb_with": []}
    straddler = None
    for a in atoms:
        y, h = a["rect"]["y"], a["rect"]["h"]
        if y < boundary_y < y + h:
            straddler = a
            break
    if straddler:
        avoid = "page-break-inside: avoid" if straddler.get("avoid") else "page-break-inside: auto"
        entry["straddling"] = (f"{straddler['selector']} (y {straddler['rect']['y']:.0f}-"
                                f"{straddler['rect']['y'] + straddler['rect']['h']:.0f}, "
                                f"h {straddler['rect']['h']:.0f}px)  {avoid}")
    else:
        before = [a for a in atoms if a["rect"]["y"] < boundary_y]
        last = max(before, key=lambda a: a["rect"]["y"], default=None)
        if last is not None and last["rect"]["h"] > H:
            entry["no_straddle_reason"] = (
                f"last atom is taller than one page (h {last['rect']['h']:.0f}px > {H:.0f}px); it flows")
        else:
            entry["no_straddle_reason"] = "no atom crosses the boundary; page ends in an explicit break"
    anchor_y = straddler["rect"]["y"] if straddler else boundary_y
    headings = [a for a in atoms if a.get("heading") and a["rect"]["y"] < anchor_y]
    h_atom = max(headings, key=lambda a: a["rect"]["y"], default=None)
    if h_atom:
        forced = "yes" if h_atom.get("break_before") else "no"
        entry["preceded_by"] = (f"{h_atom['tag']} \"{h_atom['heading']}\" at y {h_atom['rect']['y']:.0f} "
                                 f"(forced break before: {forced})")
    if reduction_target > 0:
        entry["absorb_with"] = _absorb_candidates(art, atoms, page, reduction_target)
    return entry


def _underfull_entry(art: RenderArtifacts, atoms: list[dict], page: int) -> dict | None:
    """A page that ended before its content box was full because a
    keep-together group didn't fit -- the actual mechanism behind a
    section_page miss.

    Uses the PDF page data (fill_ratio, page_map), never the unpaginated DOM
    flow, to find where the page actually ended and how much room was left:
    the DOM model alone cannot tell which page an atom actually landed on
    once explicit breaks are in play."""
    p = next((pm for pm in art.pages if pm.index == page), None)
    if p is None:
        return None
    H = art.page_content_h_px
    fill = p.fill_ratio
    remaining_px = max(0.0, (1.0 - fill) * H)
    end_rel = fill * H
    # page N spans DOM y in [(N-1)*H, N*H) -- see _page_of/_page_end_y.
    abs_end = _page_end_y(page - 1, H) + end_rel
    after = [a for a in atoms if a["rect"]["y"] >= abs_end]
    moved_atom = after[0] if after else None
    if moved_atom is None:
        return None
    dom_y = moved_atom["rect"]["y"]
    sel = moved_atom["selector"]
    heading_txt = moved_atom.get("heading")
    name = f"{moved_atom.get('tag', 'div')} \"{heading_txt}\"" if heading_txt else sel
    page_budget_end = _page_end_y(page, H)
    # fill_ratio >= 0.80 means the page was genuinely full when the atom
    # moved -- "ends early" is only true below that, when real space was
    # left on the page.
    if fill >= 0.80:
        headline = f"page {page} was full ({fill:.0%})"
        verb = f"{sel} (DOM y {dom_y:.0f}) did not fit in the {remaining_px:.0f}px left"
    elif dom_y < page_budget_end:
        # the atom's own DOM y sits inside page N's nominal budget -- Chrome,
        # not the DOM flow model, is the one that moved it to page N+1
        headline = f"page {page} ends early at y {end_rel:.0f} ({fill:.0%} full)"
        verb = (f"Chrome moved {name} (DOM y {dom_y:.0f}) to page {page + 1} "
                f"although {remaining_px:.0f}px remained")
    else:
        headline = f"page {page} ends early at y {end_rel:.0f} ({fill:.0%} full)"
        verb = (f"next atom {sel} (h {moved_atom['rect']['h']:.0f}px) needed "
                f"{moved_atom['rect']['h']:.0f}px, {remaining_px:.0f}px remained — did not fit")
    message = f"{headline}: {verb}"

    group_raw = moved_atom.get("group")
    group = group_raw[len("group:"):] if group_raw and group_raw.startswith("group:") else group_raw
    group_h = None
    if group_raw:
        # group_h spans every atom sharing the group id, including its own
        # heading -- a defensible read of the keep-together container's
        # extent, not necessarily its exact CSS height.
        members = [a for a in atoms if a.get("group") == group_raw]
        lo_y = min(a["rect"]["y"] for a in members)
        hi_y = max(a["rect"]["y"] + a["rect"]["h"] for a in members)
        group_h = hi_y - lo_y
        if group_h > remaining_px:
            cause = (f"keep-together group {group} (spans {group_h:.0f}px incl. heading, "
                     f"break-inside: avoid) does not fit in {remaining_px:.0f}px")
        else:
            cause = (f"keep-together group {group} (spans {group_h:.0f}px incl. heading, "
                     f"break-inside: avoid) fits in {remaining_px:.0f}px; check break-before "
                     f"rules on {sel}")
        suggestion = f"consider: remove break-inside: avoid on {group}, or break before {name}"
    elif moved_atom.get("avoid"):
        # the atom itself is unbreakable and no keep-together group explains
        # the move -- name the atom's own height as the cause, not a group.
        atom_h = moved_atom["rect"]["h"]
        cause = (f"{sel} is itself unbreakable (h {atom_h:.0f}px, page-break-inside: avoid) "
                 f"and needs more than the {remaining_px:.0f}px left")
        suggestion = f"consider: break before {sel}"
    else:
        heading_atom = moved_atom if moved_atom.get("heading") else next(
            (a for a in atoms if a["rect"]["y"] >= moved_atom["rect"]["y"] and a.get("heading")), None)
        where = (f"{heading_atom['tag']} \"{heading_atom['heading']}\""
                 if heading_atom else sel)
        cause = f"no keep-together group found; check break-before rules on {sel}"
        suggestion = f"consider: break before {where}"

    return {"kind": "underfull", "page": page, "fill": fill, "remaining_px": remaining_px,
            "moved_atom": sel, "moved_atom_dom_y": dom_y, "group": group,
            "group_span_px": group_h,
            "message": message, "cause": cause, "suggestion": suggestion}


def _absorb_candidates(art: RenderArtifacts, atoms: list[dict], page: int, target_px: float) -> list[str]:
    H = art.page_content_h_px
    lo, hi = _page_end_y(page - 1, H), _page_end_y(page, H)
    geom = art.dom_geometry
    boxes = [b for b in geom.get("inline_heights", []) if lo <= b["rect"]["y"] < hi]
    figs = [fg for fg in geom.get("figures", []) if lo <= fg.get("rect", {}).get("y", -1) < hi]
    candidates = boxes[:3] if boxes else []
    remaining = 3 - len(candidates)
    fig_candidates = figs[:remaining] if remaining > 0 else []
    sizes = [b["rect"]["h"] for b in candidates] + [fg["rect"]["w"] for fg in fig_candidates]
    total_size = sum(sizes)
    if not sizes or total_size <= 0:
        heading_atom = next((a for a in atoms if a["rect"]["y"] >= hi and a.get("heading")), None)
        where = f"{heading_atom['tag']} \"{heading_atom['heading']}\"" if heading_atom else "the next heading"
        return [f"no adjustable heights on this page; consider a break before {where}"]
    out = []
    for i, b in enumerate(candidates, 1):
        cur_h = b["rect"]["h"]
        share = target_px * (cur_h / total_size)
        red = min(share, cur_h / 2)
        if round(red) <= 0:   # never print "→ same (-0px)"
            continue
        new_h = cur_h - red
        cls = ".".join(b.get("classes", [])) or "sp"
        out.append(f"{cls}[{i}] height {cur_h / 96:.2g}in→{new_h / 96:.2g}in (−{red:.0f}px)")
    for fg in fig_candidates:
        cur_w = fg["rect"]["w"]
        share = target_px * (cur_w / total_size)
        red = min(share, cur_w / 2)
        if round(red) <= 0:
            continue
        new_w = cur_w - red
        sel = fg.get("selector", "svg")
        out.append(f"{sel} width {cur_w:.0f}→{new_w:.0f} (−{red:.0f}px)")
    return out


def _top_margin(art: RenderArtifacts) -> float:
    return (art.paper_h_px - art.page_content_h_px) / 2


def _rects_by_selector(art: RenderArtifacts) -> dict[str, dict]:
    g = art.dom_geometry
    out = {f["selector"]: f["rect"] for f in g.get("figures", [])}
    out.update({q["selector"]: q["rect"] for q in g.get("qa", [])})
    out.update({b["selector"]: b["rect"] for b in g.get("blocks", [])})
    return out


def finding_from_dict(d: dict) -> Finding:
    return Finding(**{k: d[k] for k in d if k in Finding.__dataclass_fields__})


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
