"""Shared types and the constants every check is measured against.

Thresholds, not knobs: a fitter searches figure sizes and CSS strategies, never
these values. Two quantities that looked like thresholds in the scaffold --
usable page height and body font size -- are properties of the document under
test and now live on RenderArtifacts, measured per render.

All geometry is CSS pixels at 96 px/in. Raster DPI is a PNG parameter and
appears in no threshold here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["hard", "soft", "info"]
Verdict = Literal["pass", "fail", "unsatisfiable", "error"]

# --- figure roles -----------------------------------------------------------
# A role is DECLARED, never inferred: `data-fig-role` on the element, or a
# class->role map in the profile. Absent both, the role is "unknown" and every
# role-scoped check degrades to `info` and is listed in skipped_checks.
FigRole = Literal["graph", "smallmultiple", "diagram", "scale", "decoration",
                  "unknown"]


@dataclass(frozen=True)
class RoleLimits:
    """What a declared role constrains.

    aspect_ratio_max   rendered width/height ceiling; None = unconstrained
    aspect_ratio_hard  whether an AR breach fails the run (False everywhere
                       today -- see the note under ROLE_LIMITS)
    height_frac_max    height / page_content_h_px ceiling (always soft)
    allow_auto_height  may height derive from the container?
    """
    aspect_ratio_max: float | None
    aspect_ratio_hard: bool
    height_frac_max: float
    allow_auto_height: bool


# Justifications, role by role. Every ceiling below is set from the MEASURED
# E0 pair, not from assertion; the measured value of the shipped document is
# quoted so the headroom is auditable.
#
# graph          Data-bearing 2-D axes. AR ceiling 2.8 and SOFT: the shipped
#                g-warm is a graph at AR 2.61, so the spec's 2.3 hard cap fails
#                the reference document, and no failure in this project's
#                history was ever an AR failure (the regression graphs are all
#                AR 1.38). Height ceiling 0.30 of the page content box = 2.9in;
#                the shipped solo figure measures 0.253 (245px) and the
#                height:auto regression measured 0.488 (473px), so 0.30 sits
#                19% above the good case and 39% below the bad one. Height must
#                never derive from the container: that inversion took the source
#                document from 5 pages to 9 -- reproduced exactly by the probe,
#                which renders the prefix fixture at 9 pages and the fixed one
#                at 5.
# smallmultiple  A cell in a grid of comparable figures. Same AR rule; tighter
#                height ceiling because eight share a page -- shipped g-pa
#                measures 140px = 0.144.
# diagram        Free-body diagrams, apparatus sketches. Proportions matter but
#                are not read quantitatively, so a wider soft AR. Allowed to be
#                large: a full-page FBD is a legitimate document.
# scale          A 1-D ruler: number line, timeline, measuring strip. Its height
#                is arbitrary and its viewBox fixes its proportions, so AR is
#                unconstrained and height:auto is the CORRECT authoring -- the
#                shipped number line is viewBox 700x88, renders 653x84 (AR 7.79)
#                with width:100%;height:auto, and is right. Bounded instead by a
#                tight height fraction (measured 0.087), which is what actually
#                protects the page.
# decoration     Rules, logos, spacers. No measured meaning; only the absolute
#                text floor applies.
# unknown        Undeclared. Fallback ceilings, nothing hard.
ROLE_LIMITS: dict[FigRole, RoleLimits] = {
    "graph":         RoleLimits(2.80, False, 0.30, False),
    "smallmultiple": RoleLimits(2.80, False, 0.20, False),
    "diagram":       RoleLimits(3.50, False, 0.45, False),
    "scale":         RoleLimits(None, False, 0.15, True),
    "decoration":    RoleLimits(None, False, 0.50, True),
    "unknown":       RoleLimits(2.80, False, 0.30, True),
}
# NOTE: aspect_ratio_hard is False for every role and there is no code path that
# sets it True. The field exists so a future document class can opt in with
# evidence; do not flip it without a measured stretched-graph failure.


# --- why no aspect ratio is HARD ------------------------------------------
# Measurement refutes the premise the scaffold's hard AR gate rested on. No
# figure in either fixture sets `preserveAspectRatio`, so every SVG uses the
# default `xMidYMid meet` and scales UNIFORMLY: rendering cannot stretch a
# graph. Measured |rendered AR - viewBox AR| across all 14 figures of both
# states is 0.1-6.7%, entirely border-box rounding.
#
# The distortion the gate was reaching for is real but arrives by one route
# only -- an explicit `preserveAspectRatio="none"` -- which is what the
# `preserve_aspect_ratio` gate checks, and which IS hard: a figure carrying
# measured meaning must never be scaled non-uniformly.
DISTORTION_WARN_FRAC = 0.10   # |rendered AR - viewBox AR| / viewBox AR

# --- page geometry ----------------------------------------------------------
# NOT a page height: the near-miss tolerance. Page 1 measured 936px against a
# 935px budget and silently orphaned one question; the spec's 10-15px range
# brackets that, and 12 is the only genuinely calibrated number in this file.
# Hard: a near-miss that is merely reported is a near-miss that is ignored.
PAGE_SLACK_TOLERANCE_PX = 12.0

# Sanity assertions for the golden document only, never divisors. US Letter is
# 612x792pt = 816x1056px; the document's @page margin of .45in leaves
# 11in - 0.9in = 10.1in = 969.6px of content height.
GOLDEN_PAPER_H_PX = 1056.0
GOLDEN_PAGE_CONTENT_H_PX = 969.6
# The probe renders prefix at 9 pages and fixed at 5 -- the spec's "5 pages to
# 9" verbatim. Page count is therefore an exact E0 assertion, not a heuristic.
GOLDEN_PAGE_COUNTS = {"fixed-worksheet": 5, "prefix-worksheet": 9}

# --- text scale -------------------------------------------------------------
# realised_px = computedFontSize * (rendered_width / viewBox_width);
# ratio = realised_px / measured body font px.
#
# The hard band is deliberately WIDE and is now derived from measurement, not
# from the spec's hand-written "0.5-0.9" guard, which was never validated
# against the document it was meant to accept and which FAILS four of that
# document's fourteen figures. Measured on the E0 pair (body 14.67px):
#
#   regression   2.26   (7pt/8pt text in a 210-unit viewBox rendered 653px)
#   shipped      0.64 - 1.11  (worst: g-pc, 210-unit viewBox scaled 1.61x by
#                              its explicit 2.55in height)
#
# A ceiling of 1.60 sits 44% above the worst accepted figure and 41% below the
# regression -- wide margin on both sides of the only separation that exists.
# This band catches factor-of-2 viewBox authoring errors and does not pretend
# to adjudicate 5% differences; that is the soft band's job.
TEXT_SCALE_FAIL = (0.40, 1.60)   # hard, empirically grounded
TEXT_SCALE_WARN = (0.55, 1.15)   # soft -- this band carries the taste

# Ratios are relative; this is not. 6pt on paper is unreadable for a 14-year-old
# at arm's length regardless of what the body text does. Absolute floor in CSS
# px at 96/in (optimisation-loop G3).
TEXT_ABS_MIN_PX = 7.0

# --- figures ----------------------------------------------------------------
# Fallback ceiling for role "unknown"; declared roles use ROLE_LIMITS. Soft,
# permanently: a full-page free-body diagram is a legitimate document, so this
# is a regression alarm and never a design rule. It is NOT in HARD_GATES and
# must not be added.
FIGURE_HEIGHT_MAX = 0.30
FIGURE_HEIGHT_WARN = 0.26

# --- fill -------------------------------------------------------------------
# A hypothesis about a comfort band, to be tested against teacher labels
# (design.md C5), not an asserted constant. Soft everywhere; the final page and
# any page ending in an explicit break are exempt (the golden document uses
# `.pb{break-before:page}` and would otherwise be red on ship day).
FILL_TARGET = 0.92
FILL_BAND = (0.88, 0.96)
FILL_SOFT_MIN = 0.80   # renamed from FILL_HARD_MIN: the name was a landmine

# blur-SSIM, if it is ever given a threshold, is a CHANGE DETECTOR and never an
# objective. Optimising it rewards a page that looks like the golden at arm's
# length, which is Goodhart with extra steps (optimisation-loop s9, adjudicated
# in implementation-plan.md Part 1 Claim 8).


@dataclass(frozen=True)
class Finding:
    id: str                       # "<check>:<selector>", stable across runs
    severity: Severity
    message: str
    value: float | None = None
    threshold: float | None = None
    page: int | None = None
    page_source: Literal["pdf", "dom_model", None] = None
    selector: str | None = None
    role: FigRole | None = None
    suggested_fix: str | None = None

    @property
    def failed(self) -> bool:
        """Only hard findings fail the run. Soft findings are always printed
        and never affect the exit code; info is advisory. Exit status derives
        from this property and nothing else."""
        return self.severity == "hard"


@dataclass(frozen=True)
class PageMetrics:
    index: int                    # 1-based
    fill_ratio: float
    slack_px: float               # page content bottom - lowest ink, from PDF
    ends_in_explicit_break: bool
    is_final: bool


@dataclass(frozen=True)
class RenderArtifacts:
    """Everything one render pass produces. Every check reads these; no check
    ever launches a browser, so every check is unit-testable against a frozen
    geometry JSON."""

    pdf_path: str
    page_png_paths: list[str]
    dom_geometry: dict
    page_count: int

    # Measured per render -- these were constants in the scaffold and were both
    # wrong for any document but one (see Part 1 F3).
    page_content_h_px: float
    page_content_w_px: float
    body_font_px: float

    pages: list[PageMetrics] = field(default_factory=list)
    fonts_resolved: list[str] = field(default_factory=list)
    fonts_missing: list[str] = field(default_factory=list)
    chrome_version: str = ""
    paper_w_px: float = 816.0     # US Letter, 612pt * 96/72
    paper_h_px: float = 1056.0    # US Letter, 792pt * 96/72
    raster_dpi: int = 150
    chrome_path: str = ""
    media_emulation: Literal["cdp", "hoisted"] = "cdp"
    page_margin_source: Literal["css_page_rule", "chrome_default"] = \
        "chrome_default"


# --- gates ----------------------------------------------------------------
# The checks whose hard findings fail a run. figure_height, aspect_ratio,
# fill_ratio and qa_split are soft/info by design and must never appear here.
HARD_GATES: tuple[str, ...] = (
    "structural", "auto_height", "figure_overflow", "text_scale",
    "page_slack", "qa_overflow", "fonts",
    # promoted 2026-10-17 after teacher calibration: 15/15 and 17/17 real
    # findings caught, 0 false alarms
    "label_collision", "arrow_shaft",
    # 2026-10-20: a page with no ink is a blank sheet in every student's copy;
    # transcript mining found 10 in session renders (2026-09-18..10-20), and no
    # document in the corpus intends one
    "blank_page",
)


class HarnessError(RuntimeError):
    """Exit 2: the harness itself could not do its job (no Chrome, unreadable
    PDF, @page cross-check mismatch, invalid profile). Never a document
    verdict."""


class ProfileError(HarnessError):
    """A profile that fails validation. Unknown keys are errors, not
    warnings: a typo'd key that silently does nothing is exactly the bug class
    this project exists to stop."""


@dataclass
class Report:
    doc: str
    profile: str | None
    verdict: Verdict
    findings: list[Finding]
    artifacts: RenderArtifacts | None
    skipped_checks: list[str] = field(default_factory=list)
    why: list = field(default_factory=list)
    fingerprint: dict | None = None

    @property
    def hard_failed(self) -> int:
        return sum(1 for f in self.findings if f.failed)
