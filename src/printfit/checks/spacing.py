"""Approach C: spacing and composition, measured on the DOM geometry.

Everything here reads `dom_geometry` (blocks, lines, qa groups, figures,
headings) and reasons about pages in a DOM MODEL. The DOM is one unpaginated
column; the model tiles it into pages of the content height and emulates the
two things print CSS does to that column:

  * a heading with `break-before: page` starts a fresh page;
  * `break-inside: avoid` -- a question group, figure, table, answer space
    or list item that would cross a page boundary and fits on a page is
    pushed whole to the next page, and everything below it moves with it;
  * whatever else the renderer did: a heading the PDF places on a later page
    than the model does (`page_map`, from the render) is anchored to that
    page, which absorbs pushes of boxes the geometry does not list as blocks.

All three are needed to reproduce the shipped references: the worksheet uses
explicit breaks on its Part headings and the answer key relies entirely on
break-inside:avoid (7 pages, no explicit breaks). Naive `y // H` tiling
splits groups in both that the PDF keeps whole. Every page-derived finding
is stamped `page_source="dom_model"`.

Checks (all `fn(artifacts, profile) -> list[Finding]`):

  self_sufficiency   a question group, its figures and its blocks share a page
  group_proximity    groups are further apart than their own contents
  macro_micro_sep    inter-block gaps exceed the line leading
  tail_slack         unused lines at the foot of a page
  largest_empty_rect biggest ink-free rectangle on a page
  composition        area shares: read text, figures, working room, structure
"""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from math import ceil

from ..types import Finding, RenderArtifacts

DEFAULT_BANDS: dict[str, tuple[float, float]] = {
    "read_text": (0.10, 0.60),
    "figures": (0.00, 0.50),
    "working_room": (0.00, 0.60),
    "structure": (0.02, 0.20),
}
BODY_LINE_FACTOR = 1.45          # body line height = body_font_px * this
TAIL_SLACK_SOFT_LINES = 6.0
EMPTY_RECT_SOFT_FRAC = 0.30
INK_KINDS = ("text", "figure", "table")
HEADING_TAGS = ("h1", "h2", "h3", "h4")
_BREAKS = ("page", "always", "left", "right")


# --- geometry helpers --------------------------------------------------------

@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    def contains(self, o: Rect, tol: float = 1.0) -> bool:
        return (o.x >= self.x - tol and o.y >= self.y - tol and
                o.right <= self.right + tol and o.bottom <= self.bottom + tol)

    def x_overlaps(self, o: Rect) -> bool:
        return min(self.right, o.right) - max(self.x, o.x) > 0

    def clip_y(self, y0: float, y1: float) -> Rect:
        top, bot = max(self.y, y0), min(self.bottom, y1)
        return Rect(self.x, top, self.w, max(0.0, bot - top))


RectFn = Callable[[dict], Rect]


def _rect(d: dict) -> Rect:
    r = d["rect"]
    return Rect(float(r["x"]), float(r["y"]), float(r["w"]), float(r["h"]))


def _outer(blocks: list[dict]) -> list[dict]:
    """Drop blocks whose rect lies inside another block's rect (td inside
    table, span inside p). Figures are always kept."""
    rects = [_rect(b) for b in blocks]
    keep = []
    for i, b in enumerate(blocks):
        if b["kind"] == "figure":
            keep.append(b)
            continue
        nested = any(j != i and rects[j].area > rects[i].area and rects[j].contains(rects[i])
                     for j in range(len(blocks)))
        if not nested:
            keep.append(b)
    return keep


def _gaps_below(blocks: list[dict], rf: RectFn = _rect) -> list[float]:
    """For each block, the vertical gap to the nearest block below it that
    overlaps it horizontally. Gaps under 1px are touching/nested boxes and
    are dropped; overlapping boxes never produce a gap."""
    rects = [rf(b) for b in blocks]
    out = []
    for a in rects:
        best = None
        for c in rects:
            if c is a or not a.x_overlaps(c):
                continue
            g = c.y - a.bottom
            if g >= 1.0 and (best is None or g < best):
                best = g
        if best is not None:
            out.append(best)
    return out


def _row_gaps(blocks: list[dict], rf: RectFn = _rect, text_only: bool = False
              ) -> list[float]:
    """Gaps between successive ROWS of blocks: each gap is the next block's top
    minus the lowest bottom seen so far, so a short table beside a tall figure
    does not report a gap the eye cannot see. With `text_only`, a gap counts
    only when the block below and the block that set the row bottom are both
    text: the margin around a figure is layout, not reading rhythm."""
    items = sorted(((rf(b), b["kind"]) for b in blocks), key=lambda t: t[0].y)
    out: list[float] = []
    running, running_kind = None, None
    for r, kind in items:
        if running is not None and r.y - running >= 1.0 and (
                not text_only or (kind == "text" and running_kind == "text")):
            out.append(r.y - running)
        if running is None or r.bottom > running:
            running, running_kind = r.bottom, kind
    return out


def _wraps_non_text(b: dict, blocks: list[dict]) -> bool:
    r = _rect(b)
    return any(c is not b and c["kind"] != "text" and r.contains(_rect(c)) for c in blocks)


# --- the page model ----------------------------------------------------------

@dataclass(frozen=True)
class ModelPage:
    index: int                  # 1-based
    y_start: float              # top of the page, in shifted (model) coordinates
    y_end: float                # y_start + content height
    ends_in_explicit_break: bool
    is_final: bool


class PageModel:
    """Tiles the DOM column into pages of height H after emulating explicit
    breaks and `break-inside: avoid`.

    The emulation is a non-decreasing shift applied to document y: at a
    break heading the shift grows so the heading lands on the next page top;
    at an avoid-item (question group, figure, table, answer space, or a text
    block wrapping one of those) that would straddle a boundary and fits on a
    page, the shift grows so the item starts the next page. Everything below
    the event moves with it, as it does in print. Items taller than a page
    cannot be kept whole and are left straddling. `eff()` returns a block's
    rect in shifted coordinates; all page arithmetic uses those."""

    def __init__(self, artifacts: RenderArtifacts):
        self.H = float(artifacts.page_content_h_px)
        self.W = float(artifacts.page_content_w_px)
        geom = artifacts.dom_geometry
        blocks = geom.get("blocks", [])
        # (y, kind, h): kind 0 = explicit break, 1 = avoid item, 2 = anchor to
        # the PDF page `h` where the renderer found this heading's text
        events: list[tuple[float, int, float]] = []
        pmap = geom.get("page_map") or {}
        for h in geom.get("headings", []):
            y = float(h["rect"]["y"])
            if h.get("break_before") in _BREAKS and y > 0:
                events.append((y, 0, 0.0))
            elif pmap.get(h.get("text")) and y > 0:
                events.append((y, 2, float(pmap[h["text"]])))
        for q in geom.get("qa", []):
            events.append((_rect(q).y, 1, _rect(q).h))
        for b in blocks:
            if b["kind"] in ("figure", "table", "space") or (
                    b["kind"] == "text" and _wraps_non_text(b, blocks)):
                events.append((_rect(b).y, 1, _rect(b).h))
        events.sort(key=lambda e: (e[0], e[1], -e[2]))
        H = self.H
        step_y, step_off = [float("-inf")], [0.0]
        offset = 0.0
        self.break_pages: set[int] = set()
        for y, kind, h in events:
            ey = y + offset
            k = int(ey // H)                            # 0-based page of the top
            boundary = (k + 1) * H
            if kind == 0:
                if ey - k * H > 1e-6:
                    self.break_pages.add(k + 1)
                    offset += boundary - ey
                elif k >= 1:                # already on a page top
                    self.break_pages.add(k)
            elif kind == 2:
                if int(h) - 1 > k:          # PDF has it later: something above was pushed
                    offset += (int(h) - 1) * H - ey
            elif h <= H and ey + h - boundary > 1e-6:
                offset += boundary - ey
            if offset != step_off[-1]:
                step_y.append(y)
                step_off.append(offset)
        self._step_y, self._step_off = step_y, step_off
        doc_end = 0.0
        for coll in ("blocks", "qa", "figures"):
            for d in geom.get(coll, []):
                doc_end = max(doc_end, self.eff(d).bottom)
        n = max(1, ceil(doc_end / H - 1e-9))
        self.pages = [ModelPage(index=k, y_start=(k - 1) * H, y_end=k * H,
                                ends_in_explicit_break=k in self.break_pages and k < n,
                                is_final=k == n) for k in range(1, n + 1)]

    def shift(self, y: float) -> float:
        return self._step_off[bisect_right(self._step_y, y) - 1]

    def eff(self, d: dict) -> Rect:
        r = _rect(d)
        return Rect(r.x, r.y + self.shift(r.y), r.w, r.h)

    def page_of(self, y: float, shifted: bool = False) -> int:
        ey = y if shifted else y + self.shift(y)
        return max(1, min(len(self.pages), int(ey // self.H) + 1))

    def page(self, index: int) -> ModelPage:
        return self.pages[index - 1]

    def on_page(self, items: list[dict], index: int) -> list[dict]:
        """Items whose (shifted) top falls on page `index`."""
        return [d for d in items if self.page_of(self.eff(d).y, shifted=True) == index]


def _ink_blocks(artifacts: RenderArtifacts) -> list[dict]:
    return _outer([b for b in artifacts.dom_geometry.get("blocks", [])
                   if b["kind"] in INK_KINDS])


def _group_key(q: dict) -> set[str]:
    keys = {q["selector"]}
    if q.get("qid"):
        keys.add(q["qid"])
    return keys


# --- 1. self_sufficiency -----------------------------------------------------

def self_sufficiency(artifacts: RenderArtifacts, profile: dict) -> list[Finding]:
    """HARD. A question group must not split across pages, and everything it
    owns -- figures whose centre lies inside it, blocks nested in it, blocks
    that name it via data-for -- must sit on the page the group starts on.
    With break-inside emulated, a group splits only when it cannot fit on a
    page, or when what it owns has been pushed away from it."""
    geom = artifacts.dom_geometry
    model = PageModel(artifacts)
    out: list[Finding] = []
    blocks = geom.get("blocks", [])
    figures = geom.get("figures", [])
    for q in geom.get("qa", []):
        r = model.eff(q)
        top_page = model.page_of(r.y, shifted=True)
        bot_page = model.page_of(r.bottom - 1, shifted=True)
        problems: list[str] = []
        if top_page != bot_page:
            problems.append(f"group spans pages {top_page}-{bot_page}")
        raw = _rect(q)
        for f in figures:
            fr = _rect(f)
            cx, cy = fr.x + fr.w / 2, fr.y + fr.h / 2
            if raw.x <= cx <= raw.right and raw.y <= cy <= raw.bottom:
                fp = model.page_of(model.eff(f).y + fr.h / 2, shifted=True)
                if fp != top_page:
                    problems.append(f"figure {f['selector']} is on page {fp}")
        keys = _group_key(q)
        for b in blocks:
            if b.get("qa") in keys:
                br = model.eff(b)
                bp = {model.page_of(br.y, shifted=True), model.page_of(br.bottom - 1, shifted=True)}
                if bp != {top_page}:
                    problems.append(f"block {b['selector']} is on page "
                                    f"{'-'.join(str(p) for p in sorted(bp))}")
        for b in blocks:
            if b.get("data_for") and any(k in keys for k in str(b["data_for"]).split()):
                bp = model.page_of(model.eff(b).y, shifted=True)
                if bp != top_page:
                    problems.append(f"{b['selector']} (data-for) is on page {bp}")
        fid = f"self_sufficiency:{q['selector']}"
        if problems:
            out.append(Finding(id=fid, severity="hard", selector=q["selector"],
                               page=top_page, page_source="dom_model",
                               value=float(len(problems)), threshold=0.0,
                               message=f"{q['selector']} is not self-sufficient on page "
                                       f"{top_page}: " + "; ".join(problems),
                               suggested_fix="keep the group and its figure together: "
                                             "shrink the figure or move the group"))
        else:
            out.append(Finding(id=fid, severity="info", selector=q["selector"],
                               page=top_page, page_source="dom_model", value=0.0,
                               threshold=0.0,
                               message=f"{q['selector']} is whole on page {top_page}"))
    return out


# --- 2. group_proximity ------------------------------------------------------

# Measured on the E0 references with ink-based gaps (answer space is white)
# and the intra-group rhythm taken from text-to-text gaps:
#   fixed-worksheet   p1 12.5   p3 1.00   p4 59.2     (multi-group pages)
#   fixed-key         p1 1.25   p3 1.43   p4 8.75
#   prefix-worksheet  p5 1.00
# The worksheet's groups and their prompts share one 7px margin (`.q`), so
# page 3 sits exactly at 1.0; the 0.05 tolerance absorbs sub-pixel rounding
# of border-box rects and nothing else.
GROUP_PROXIMITY_HARD = 0.95


def group_proximity(artifacts: RenderArtifacts, profile: dict) -> list[Finding]:
    """Per page: R = min ink gap between consecutive question groups / max gap
    between rows of TEXT inside any group. HARD when R < 1 (less rounding):
    the groups are closer to each other than their own prompts are.

    Gaps are measured between INK (text, figures, tables). Blank answer space
    is what separates groups in the reference, and a box-rect gap would count
    it as content. The intra-group statistic uses text rows only: the gap
    around a figure is its layout margin, not the group's reading rhythm
    (the key's page 1 has a 12px figure margin against 10px between groups
    and is accepted)."""
    geom = artifacts.dom_geometry
    model = PageModel(artifacts)
    ink = _ink_blocks(artifacts)
    out: list[Finding] = []
    for p in model.pages:
        groups = model.on_page(geom.get("qa", []), p.index)
        if len(groups) < 2:
            continue
        spans, inside = [], []
        for g in groups:
            members = [b for b in ink if b.get("qa") in _group_key(g)]
            if not members:
                continue
            rs = [model.eff(b) for b in members]
            spans.append((min(r.y for r in rs), max(r.bottom for r in rs)))
            inside += _row_gaps(members, model.eff, text_only=True)
        spans.sort()
        between = [b[0] - a[1] for a, b in pairwise(spans) if b[0] - a[1] >= 1.0]
        if not between or not inside:
            continue
        min_between, max_inside = min(between), max(inside)
        R = min_between / max_inside
        fid = f"group_proximity:page-{p.index}"
        if R < GROUP_PROXIMITY_HARD:
            out.append(Finding(id=fid, severity="hard", page=p.index, page_source="dom_model",
                               value=round(R, 2), threshold=GROUP_PROXIMITY_HARD,
                               message=f"page {p.index}: groups are {min_between:.0f}px apart "
                                       f"but their contents are up to {max_inside:.0f}px apart "
                                       f"(R={R:.2f}); groups do not read as units",
                               suggested_fix=f"add at least {max_inside - min_between:.0f}px "
                                             "between question groups"))
        else:
            out.append(Finding(id=fid, severity="info", page=p.index, page_source="dom_model",
                               value=round(R, 2), threshold=GROUP_PROXIMITY_HARD,
                               message=f"page {p.index}: group gap {min_between:.0f}px / "
                                       f"internal gap {max_inside:.0f}px = {R:.2f}"))
    return out


# --- 3. macro_micro_sep ------------------------------------------------------

def _leadings(lines: list[dict]) -> list[float]:
    by_block: dict[str, list[float]] = {}
    for ln in lines:
        by_block.setdefault(ln["block"], []).append(float(ln["y_top"]))
    out = []
    for tops in by_block.values():
        tops.sort()
        out += [b - a for a, b in pairwise(tops) if b - a >= 1.0]
    return out


# The design asked for HARD below 1.0 and soft below 1.4. Measured on the
# accepted references the per-page ratio is 0.07-0.28 on EVERY page of both:
# prompts carry a 7px margin against 21px leading, and the 2-3px gaps are
# title/subtitle and caption/figure pairs. Restricting to multi-line blocks
# gives 0.24-0.68. The broken prefix state measures 0.05-0.65 -- no
# separation either way. A threshold that has no separation and fails the
# reference is not a gate, so by default the ratio is reported as info; a
# document class that carries its grouping in whitespace can pass thresholds
# explicitly (see the `hard_below` / `soft_below` parameters).
MACRO_MICRO_HARD: float | None = None
MACRO_MICRO_SOFT: float | None = None


def macro_micro_sep(artifacts: RenderArtifacts, profile: dict,
                    hard_below: float | None = MACRO_MICRO_HARD,
                    soft_below: float | None = MACRO_MICRO_SOFT) -> list[Finding]:
    """Per page: min inter-block ink gap / max line leading. Blocks set closer
    than their own lines cannot be told apart by whitespace alone."""
    geom = artifacts.dom_geometry
    model = PageModel(artifacts)
    ink = _ink_blocks(artifacts)
    lines = geom.get("lines", [])
    out: list[Finding] = []
    for p in model.pages:
        page_lines = [ln for ln in lines if model.page_of(float(ln["y_top"])) == p.index]
        leadings = _leadings(page_lines)
        gaps = _gaps_below(model.on_page(ink, p.index), model.eff)
        if not leadings or not gaps:
            continue
        min_gap, max_lead = min(gaps), max(leadings)
        R = min_gap / max_lead
        fid = f"macro_micro_sep:page-{p.index}"
        msg = (f"page {p.index}: min block gap {min_gap:.0f}px / max leading "
               f"{max_lead:.0f}px = {R:.2f}")
        if hard_below is not None and R < hard_below:
            out.append(Finding(id=fid, severity="hard", page=p.index, page_source="dom_model",
                               value=round(R, 2), threshold=hard_below, message=msg +
                               "; blocks are closer than their own lines",
                               suggested_fix=f"raise block margins to at least {max_lead:.0f}px"))
        elif soft_below is not None and R < soft_below:
            out.append(Finding(id=fid, severity="soft", page=p.index, page_source="dom_model",
                               value=round(R, 2), threshold=soft_below, message=msg))
        else:
            out.append(Finding(id=fid, severity="info", page=p.index, page_source="dom_model",
                               value=round(R, 2), threshold=hard_below, message=msg))
    return out


# --- 4. tail_slack -----------------------------------------------------------

def tail_slack(artifacts: RenderArtifacts, profile: dict) -> list[Finding]:
    """Per non-final page not ending in an explicit break: empty lines below
    the last block, in body line heights. Soft above 6 lines. A plain
    paragraph crossing the boundary splits, so that page counts as full."""
    model = PageModel(artifacts)
    line_h = float(artifacts.body_font_px) * BODY_LINE_FACTOR
    blocks = artifacts.dom_geometry.get("blocks", [])
    out: list[Finding] = []
    for p in model.pages:
        if p.is_final or p.ends_in_explicit_break:
            continue
        on = [model.eff(b) for b in model.on_page(blocks, p.index)]
        if not on:
            continue
        slack_px = max(0.0, p.y_end - max(r.bottom for r in on))
        n = slack_px / line_h
        fid = f"tail_slack:page-{p.index}"
        if n > TAIL_SLACK_SOFT_LINES:
            out.append(Finding(id=fid, severity="soft", page=p.index, page_source="dom_model",
                               value=round(n, 1), threshold=TAIL_SLACK_SOFT_LINES,
                               message=f"page {p.index} ends {n:.1f} lines ({slack_px:.0f}px) "
                                       "early without an explicit break",
                               suggested_fix="pull the next block up or add answer space"))
        else:
            out.append(Finding(id=fid, severity="info", page=p.index, page_source="dom_model",
                               value=round(n, 1), threshold=TAIL_SLACK_SOFT_LINES,
                               message=f"page {p.index} tail slack {n:.1f} lines"))
    return out


# --- 5. largest_empty_rect ---------------------------------------------------

def _largest_band(rects: list[Rect], y0: float, y1: float, x0: float, x1: float
                  ) -> tuple[float, float, float]:
    """Largest y-gap free of any rect overlapping [x0, x1]: (top, height, area)."""
    ivs = sorted((r.y, r.bottom) for r in rects
                 if min(r.right, x1) - max(r.x, x0) > 0 and r.bottom > y0 and r.y < y1)
    best = (y0, 0.0)
    cursor = y0
    for a, b in ivs:
        if a - cursor > best[1]:
            best = (cursor, a - cursor)
        cursor = max(cursor, b)
    if y1 - cursor > best[1]:
        best = (cursor, y1 - cursor)
    return best[0], best[1], best[1] * (x1 - x0)


def largest_empty_rect(artifacts: RenderArtifacts, profile: dict) -> list[Finding]:
    """Per page: the largest ink-free rectangle, as a fraction of the page.
    Ink = text, figure and table blocks; answer space is purposeful and does
    not count as ink. Soft above 0.30 on a page that had no reason to end."""
    model = PageModel(artifacts)
    W = model.W
    ink = _ink_blocks(artifacts)
    page_x0 = min((_rect(b).x for b in ink), default=0.0)
    out: list[Finding] = []
    for p in model.pages:
        rects = [model.eff(b).clip_y(p.y_start, p.y_end) for b in ink]
        rects = [r for r in rects if r.h > 0]
        cands = []
        for x0, x1 in ((page_x0, page_x0 + W), (page_x0, page_x0 + W / 2),
                       (page_x0 + W / 2, page_x0 + W)):
            top, h, area = _largest_band(rects, p.y_start, p.y_end, x0, x1)
            cands.append((area, Rect(x0 - page_x0, top - p.y_start, x1 - x0, h)))
        area, r = max(cands, key=lambda c: c[0])
        frac = area / (W * model.H)
        fid = f"largest_empty_rect:page-{p.index}"
        rect_s = f"x={r.x:.0f} y={r.y:.0f} w={r.w:.0f} h={r.h:.0f}"
        exempt = p.is_final or p.ends_in_explicit_break
        if frac > EMPTY_RECT_SOFT_FRAC and not exempt:
            out.append(Finding(id=fid, severity="soft", page=p.index, page_source="dom_model",
                               value=round(frac, 3), threshold=EMPTY_RECT_SOFT_FRAC,
                               message=f"page {p.index}: largest empty rectangle is "
                                       f"{frac:.0%} of the page ({rect_s})",
                               suggested_fix="fill the hole with the next block or turn it "
                                             "into declared answer space"))
        else:
            out.append(Finding(id=fid, severity="info", page=p.index, page_source="dom_model",
                               value=round(frac, 3), threshold=EMPTY_RECT_SOFT_FRAC,
                               message=f"page {p.index}: largest empty rectangle "
                                       f"{frac:.0%} ({rect_s})"))
    return out


# --- 6. composition ----------------------------------------------------------

def page_shares(artifacts: RenderArtifacts, profile: dict, p: ModelPage,
                model: PageModel | None = None) -> dict[str, float]:
    """Area shares of one model page: read_text, figures, working_room,
    structure, air."""
    model = model or PageModel(artifacts)
    geom = artifacts.dom_geometry
    page_area = model.W * model.H
    ws_classes = set(profile.get("workspace_classes") or [])
    blocks = _outer(geom.get("blocks", []))
    acc = {"read_text": 0.0, "figures": 0.0, "working_room": 0.0, "structure": 0.0}
    for b in blocks:
        r = model.eff(b).clip_y(p.y_start, p.y_end)
        if r.h <= 0:
            continue
        if b["kind"] == "space" or ws_classes.intersection(b.get("classes") or []):
            acc["working_room"] += r.area
        elif b["kind"] == "figure":
            acc["figures"] += r.area
        elif b["tag"] in HEADING_TAGS:
            continue                      # counted from `headings`
        else:
            acc["read_text"] += r.area
    for h in geom.get("headings", []):
        acc["structure"] += model.eff(h).clip_y(p.y_start, p.y_end).area
    shares = {k: v / page_area for k, v in acc.items()}
    shares["air"] = max(0.0, 1.0 - sum(shares.values()))
    return shares


def composition(artifacts: RenderArtifacts, profile: dict) -> list[Finding]:
    """Per page: area shares against bands. Soft when a share is out of band on
    a non-final page; one info per page carries all shares."""
    model = PageModel(artifacts)
    bands = profile.get("composition") or DEFAULT_BANDS
    out: list[Finding] = []
    for p in model.pages:
        shares = page_shares(artifacts, profile, p, model)
        summary = ", ".join(f"{k} {v:.0%}" for k, v in shares.items())
        for name, (lo, hi) in bands.items():
            v = shares.get(name)
            if v is None or lo <= v <= hi:
                continue
            sev = "info" if p.is_final else "soft"
            out.append(Finding(id=f"composition:page-{p.index}:{name}", severity=sev,
                               page=p.index, page_source="dom_model", value=round(v, 3),
                               threshold=lo if v < lo else hi,
                               message=f"page {p.index}: {name} is {v:.0%}, outside "
                                       f"{lo:.0%}-{hi:.0%} ({summary})"))
        out.append(Finding(id=f"composition:page-{p.index}:shares", severity="info",
                           page=p.index, page_source="dom_model",
                           message=f"page {p.index}: {summary}"))
    return out


# --- registry ----------------------------------------------------------------

CHECKS = (self_sufficiency, group_proximity, macro_micro_sep, tail_slack,
          largest_empty_rect, composition)


def run(artifacts: RenderArtifacts, profile: dict) -> list[Finding]:
    out: list[Finding] = []
    for fn in CHECKS:
        out.extend(fn(artifacts, profile))
    return out


def verdict(artifacts: RenderArtifacts, profile: dict) -> tuple[str, list[Finding]]:
    findings = run(artifacts, profile)
    return ("fail" if any(f.failed for f in findings) else "pass"), findings
