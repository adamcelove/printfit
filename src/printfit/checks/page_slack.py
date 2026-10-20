"""Per-page slack and page-splitting -- catches the silently orphaned question.

Page 1 measured 936px against a 935px budget. The only visible symptom was one
question appearing on the following page: no warning, no partial failure. The
lesson is that the budget must be `usable - tolerance` and that slack must be
*reported per page*, so a near-miss is a number rather than something a human
happens to notice.
"""
from __future__ import annotations

from ..types import (FILL_BAND, FILL_SOFT_MIN, HARD_GATES, PAGE_SLACK_TOLERANCE_PX, Finding,
                     RenderArtifacts)


def run(artifacts: RenderArtifacts, profile: dict) -> list[Finding]:
    """Report slack for every page; fail any page below tolerance."""
    out: list[Finding] = []
    for p in artifacts.pages:
        if p.slack_px < PAGE_SLACK_TOLERANCE_PX and not p.is_final and p.slack_px < 1.0:
            # ink to within a pixel of the edge: Chrome split a box (or text)
            # across the break, so the page reads full whatever small cut is made
            out.append(Finding(id=f"page_slack:page-{p.index}", severity="hard",
                               value=round(p.slack_px, 1), threshold=PAGE_SLACK_TOLERANCE_PX,
                               page=p.index, page_source="pdf",
                               message=f"page {p.index} is full to the edge (slack {p.slack_px:.1f}px): "
                                       "content runs across the break, so a cut smaller than the "
                                       "part that continues on the next page leaves it full",
                               suggested_fix="run check --why: it names what was split and how much "
                                             "continues; fit it whole, move it whole, or split it in the source"))
        elif p.slack_px < PAGE_SLACK_TOLERANCE_PX and not p.is_final:
            out.append(Finding(id=f"page_slack:page-{p.index}", severity="hard",
                               value=round(p.slack_px, 1), threshold=PAGE_SLACK_TOLERANCE_PX,
                               page=p.index, page_source="pdf",
                               message=f"page {p.index} slack {p.slack_px:.0f}px < "
                                       f"{PAGE_SLACK_TOLERANCE_PX:.0f}px: one line of growth "
                                       "orphans the last block onto the next page",
                               suggested_fix="shrink a figure or answer space on this page by "
                                             f"{PAGE_SLACK_TOLERANCE_PX - p.slack_px + 12:.0f}px"))
        else:
            out.append(Finding(id=f"page_slack:page-{p.index}", severity="info",
                               value=round(p.slack_px, 1), threshold=PAGE_SLACK_TOLERANCE_PX,
                               page=p.index, page_source="pdf",
                               message=f"page {p.index} slack {p.slack_px:.0f}px"
                                       + (" (final page: nothing to orphan)" if p.is_final
                                          and p.slack_px < PAGE_SLACK_TOLERANCE_PX else "")))
    for p in artifacts.pages:
        if p.fill_ratio <= 0.0:
            out.append(Finding(id=f"blank_page:page-{p.index}",
                               severity="hard" if "blank_page" in HARD_GATES else "soft", value=0.0,
                               page=p.index, page_source="pdf",
                               message=f"page {p.index} prints as a blank sheet: whatever landed "
                                       "on it has no ink (an empty answer box or a white panel "
                                       f"that ran past page {p.index - 1})",
                               suggested_fix=f"run check --why for what spilled from page "
                                             f"{p.index - 1} and how much room it needs"))
    out += fill_ratio(artifacts, profile)
    out += qa_overflow(artifacts)
    out += qa_split(artifacts)
    if profile.get("pages") and artifacts.page_count != profile["pages"]:
        out.append(Finding(id="page_count", severity="hard", value=float(artifacts.page_count),
                           threshold=float(profile["pages"]), page_source="pdf",
                           message=f"document is {artifacts.page_count} pages; profile requires "
                                   f"{profile['pages']}"))
    for heading, want in (profile.get("section_pages") or {}).items():
        got = _lookup(artifacts.dom_geometry.get("page_map", {}), heading)
        if got is not None and got != want:
            out.append(Finding(id=f"section_page:{heading}", severity="hard",
                               value=float(got), threshold=float(want), page=got, page_source="pdf",
                               message=f"section '{heading}' is on page {got}; profile requires {want}"))
    return out


def _lookup(pmap: dict, heading: str):
    for k, v in pmap.items():
        if heading.lower() in k.lower():
            return v
    return None


def fill_ratio(artifacts: RenderArtifacts, profile: dict | None = None) -> list[Finding]:
    """Soft. Final page and pages ending in an explicit break are exempt."""
    cfg = (profile or {}).get("fill") or {}
    if cfg.get("enabled", True) is False:
        return []
    out = []
    for p in artifacts.pages:
        if p.is_final and cfg.get("skip_final_page", True):
            continue
        if p.ends_in_explicit_break and cfg.get("skip_explicit_break_pages", True):
            continue
        if p.fill_ratio < FILL_SOFT_MIN:
            out.append(Finding(id=f"fill_ratio:page-{p.index}", severity="soft",
                               value=round(p.fill_ratio, 3), threshold=FILL_SOFT_MIN,
                               page=p.index, page_source="pdf",
                               message=f"page {p.index} is {p.fill_ratio:.0%} full; below the "
                                       f"{FILL_SOFT_MIN:.0%} comfort floor (band "
                                       f"{FILL_BAND[0]:.0%}-{FILL_BAND[1]:.0%})"))
    return out


def qa_overflow(artifacts: RenderArtifacts) -> list[Finding]:
    """Hard when a question group is taller than a page: it cannot be kept
    together and will silently overflow."""
    H = artifacts.page_content_h_px
    return [Finding(id=f"qa_overflow:{q['selector']}", severity="hard", selector=q["selector"],
                    value=round(q["offset_height"] / H, 3), threshold=1.0,
                    page=int(q["offset_top"] // H) + 1, page_source="dom_model",
                    message=f"{q['selector']} is {q['offset_height']:.0f}px tall, taller than "
                            f"the {H:.0f}px page")
            for q in artifacts.dom_geometry.get("qa", []) if q["offset_height"] > H]


def qa_split(artifacts: RenderArtifacts) -> list[Finding]:
    """Info: a question group straddling a DOM-model page boundary. The DOM is
    unpaginated so this is a model, not the PDF truth."""
    H = artifacts.page_content_h_px
    out = []
    for q in artifacts.dom_geometry.get("qa", []):
        top, bot = q["offset_top"], q["offset_top"] + q["offset_height"]
        if int(top // H) != int((bot - 1) // H):
            out.append(Finding(id=f"qa_split:{q['selector']}", severity="info",
                               selector=q["selector"], page=int(top // H) + 1,
                               page_source="dom_model",
                               message=f"{q['selector']} straddles a page boundary in the "
                                       "unpaginated DOM model"))
    return out
