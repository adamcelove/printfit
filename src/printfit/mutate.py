"""Synthetic regressions. Each mutation injects ONE known defect into a good
document and returns the mutated source, or None when the document has
nothing for that mutation to act on. The evaluator labels every product
`bad` with the mutation name as the reason.

Every mutation is a text edit on the HTML source; none needs a browser.
"""
from __future__ import annotations

import re

_SVG_OPEN = re.compile(r"<svg\b([^>]*)>", re.I)
_VB = re.compile(r"viewBox\s*=\s*\"\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*\"", re.I)
_QA = re.compile(r"<(div|section)\b[^>]*class=\"[^\"]*\bqa\b[^\"]*\"[^>]*>", re.I)
_H2 = re.compile(r"<h2\b", re.I)


def _append_style(src: str, css: str) -> str:
    i = src.lower().rfind("</style>")
    if i >= 0:
        return src[:i] + css + src[i:]
    return src + f"<style>{css}</style>"


def _first_svg_classes(src: str) -> list[str]:
    m = _SVG_OPEN.search(src)
    if not m:
        return []
    c = re.search(r"class=\"([^\"]*)\"", m.group(1))
    return c.group(1).split() if c else []


def auto_height(src: str) -> str | None:
    """Height-source inversion: every SVG takes its height from its column.
    The exact root cause of the 5-to-9-page regression."""
    if not _SVG_OPEN.search(src):
        return None
    if re.search(r"svg[^{]*\{[^}]*height\s*:\s*auto", src) and \
            not re.search(r"svg[^{]*\{[^}]*height\s*:\s*[\d.]+(in|px|pt)", src):
        return None                     # already auto everywhere: no-op
    return _append_style(src, "\nsvg{width:100% !important;height:auto !important}")


def viewbox_shrink(src: str) -> str | None:
    """Author every viewBox a third as wide while keeping the render width:
    in-figure text realises 3x larger. The supersized-number-line regression."""
    if not _VB.search(src):
        return None

    def fix(m: re.Match) -> str:
        a, b, w, h = (float(x) for x in m.groups())
        return f'viewBox="{a/3:g} {b/3:g} {w/3:g} {h/3:g}"'

    out = _VB.sub(fix, src)
    # scale the drawing so geometry stays inside the smaller box; text keeps
    # its user-unit font size, which is the point
    out = re.sub(r"(<svg\b[^>]*>)", r'\1<g transform="scale(0.33333)">', out, flags=re.I)
    out = re.sub(r"</svg>", "</g></svg>", out, flags=re.I)
    return out


def duplicate_section(src: str) -> str | None:
    """Copy the second <h2> section after itself: content duplication."""
    hs = [m.start() for m in _H2.finditer(src)]
    if len(hs) < 3:
        return None
    i, j = hs[1], hs[2]
    return src[:j] + src[i:j] + src[j:]


def drop_qa(src: str) -> str | None:
    """Delete the second question group: content loss."""
    ms = list(_QA.finditer(src))
    if len(ms) < 2:
        return None
    m = ms[1]
    tag = m.group(1)
    depth, i = 0, m.start()
    opener = re.compile(rf"<{tag}\b|</{tag}>", re.I)
    for t in opener.finditer(src, m.start()):
        depth += 1 if not t.group(0).startswith("</") else -1
        if depth == 0:
            return src[:i] + src[t.end():]
    return None


def giant_gap(src: str) -> str | None:
    """A five-inch hole before the second section heading."""
    hs = [m.start() for m in _H2.finditer(src)]
    if len(hs) < 2:
        return None
    j = hs[1]
    return src[:j] + '<div class="mut-gap" style="height:5in"></div>' + src[j:]


def huge_figure(src: str) -> str | None:
    """The first figure taller than a page: cannot break, silently overflows."""
    cls = _first_svg_classes(src)
    sel = "svg" + "".join("." + c for c in cls) if cls else "svg"
    if not _SVG_OPEN.search(src):
        return None
    return _append_style(src, f"\n{sel}{{height:10.2in !important;width:auto !important;max-width:100% !important}}")


def tiny_text(src: str) -> str | None:
    """Every in-figure label at 4px: below the absolute legibility floor."""
    if not re.search(r"<text\b", src, re.I):
        return None
    return _append_style(src, "\nsvg text,svg tspan{font-size:4px !important}")


def cramped(src: str) -> str | None:
    """Collapse every vertical margin: groups sit closer together than their
    own lines, and the page reads as one undifferentiated column."""
    return _append_style(src, "\nbody *{margin-top:0 !important;margin-bottom:0 !important;"
                              "padding-top:0 !important;padding-bottom:0 !important}")


_DIV_OPEN_LINE = re.compile(r'^([ \t]*)<div\b[^>]*\bclass="[^"]*"[^>]*>[ \t]*$', re.MULTILINE)
_DIV_QA_OPEN_LINE = re.compile(
    r'^([ \t]*)<div\b[^>]*\bclass="[^"]*\b(?:q|prob|mcq|qa)\b[^"]*"[^>]*>[ \t]*$', re.MULTILINE)


def split_div(src: str) -> str | None:
    """Move the opening line of the first multi-line `<div class="...">` to
    just after the last `<h2>`, stranding its tail. Reproduces the real
    2026-09-17 corruption: counts and total text length do not change, but a
    block's own nesting does."""
    m = _DIV_OPEN_LINE.search(src)
    h2s = list(_H2.finditer(src))
    if not m or not h2s:
        return None
    line_start = src.rfind("\n", 0, m.start()) + 1
    line_end = src.find("\n", m.end())
    line_end = line_end + 1 if line_end != -1 else len(src)
    moved = src[line_start:line_end]
    rest = src[:line_start] + src[line_end:]
    # re-anchor the insertion point in `rest`, after the removal
    last_h2_start = max(h.start() for h in _H2.finditer(rest))
    h2_line_end = rest.find("\n", last_h2_start)
    h2_line_end = h2_line_end + 1 if h2_line_end != -1 else len(rest)
    return rest[:h2_line_end] + moved + rest[h2_line_end:]


def move_by_line(src: str) -> str | None:
    """Move the opening line of the first multi-line `div.q|prob|mcq|qa`
    three lines down."""
    m = _DIV_QA_OPEN_LINE.search(src)
    if not m:
        return None
    lines = src.split("\n")
    line_no = src.count("\n", 0, m.start())
    if line_no + 3 >= len(lines):
        return None
    line = lines.pop(line_no)
    lines.insert(line_no + 3, line)
    return "\n".join(lines)


MUTATIONS = {
    "auto_height": auto_height,
    "viewbox_shrink": viewbox_shrink,
    "duplicate_section": duplicate_section,
    "drop_qa": drop_qa,
    "giant_gap": giant_gap,
    "huge_figure": huge_figure,
    "tiny_text": tiny_text,
    "cramped": cramped,
    "split_div": split_div,
    "move_by_line": move_by_line,
}

# Which approach is EXPECTED to catch which defect. This is the hypothesis the
# evaluation tests; a miss against expectation is a finding about the approach.
EXPECTED = {
    "auto_height":       {"gates"},
    "viewbox_shrink":    {"gates"},
    "duplicate_section": set(),           # structural.compare, a before/after check, not a verdict
    "drop_qa":           set(),
    "giant_gap":         {"raster", "spacing"},
    "huge_figure":       {"gates", "raster"},
    "tiny_text":         {"gates"},
    "cramped":           {"spacing"},
    "split_div":         set(),           # structural.compare, a before/after check, not a verdict
    "move_by_line":      set(),
}
