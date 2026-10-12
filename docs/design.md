# Design memo: catching print-aesthetic regressions in the worksheet fitter

**Scope note on sources.** There is no separate failure-log file in
`the source repository`. The repo has two commits (`2cbae3d`, `d094d18`)
and one document under `docs/superpowers/`. The failure catalogue is embedded in
§4 of the spec itself
(`docs/superpowers/specs/2026-08-31-printable-html-fitting-design.md`,
lines 77–142), and the *remediation* of the two aesthetic regressions is legible
in the diff of `generators/u1-vt-graphs.py`
in commit `d094d18`. Both sources agree, which lets each complaint be pinned to
the exact CSS/SVG property that was wrong. Line citations below are to the spec
file unless otherwise noted.

---

## 0. What the teacher actually flagged

The spec is explicit that this is a real transcript, not an illustration
(`spec:15-16`):

> "Every failure listed in §4 actually happened during that session; the numbers
> are the measured ones, not illustrations."

The aesthetic complaint is one sentence, §4.7 (`spec:136-142`):

> **"Both the oversized graphs and the supersized number line satisfied every
> numeric constraint and were caught only by a human looking at the page. Any
> loop that stops at geometric success will ship documents that look wrong."**

So there are exactly **two** things the teacher pointed at, and the spec traces
each to a root cause elsewhere in §4.

### Complaint 1 — "oversized graphs"

Root cause §4.2 (`spec:90-98`):

> "SVGs styled `width:100%; height:auto` take their height from whatever column
> they land in. Widening the page body to use more of the paper made every graph
> **taller**, and the document went from 5 pages to 9. Later, one graph measured
> 473px tall (~4.9in) purely from inheriting a wide container."

473px is 4.9in of a 9.7in usable page — one graph eating half a page. The fix is
visible in the diff: `svg.grid{width:100%;height:auto}` became

```css
svg.grid{display:block;width:auto;height:1.45in;max-width:100%;margin:0 auto;
         border:1px solid var(--rule);background:#fff}
svg.g-warm{height:1.6in}
svg.g-pa{height:1.46in}
svg.g-pb{height:2.37in}
svg.g-pc{height:2.55in}
```

The regression is **height-source inversion**: height became a dependent
variable of column width. The `grid()` helper also gained a `W` parameter so
each figure's viewBox width is authored per role (`W=400` for the warm-up,
`W=310` for the Part A small-multiples), rather than every figure sharing one
210-unit viewBox.

### Complaint 2 — "supersized number line"

Root cause §4.3 (`spec:100-109`):

> "An SVG authored in a 210-unit-wide viewBox, rendered 700px wide, scales its
> own 7pt labels by 3.33× — they render ~31px and appear 'supersized' beside
> 14.7px body text. The same graph in a narrow column renders its labels too
> small."

The diff confirms the fix: `numline()` was re-authored from
`viewBox="0 0 210 74"` to `viewBox="0 0 700 88"`, the shared `.tk` tick class
was replaced by dedicated `.nlk{font:10px Arial;fill:#333}` and
`.nla{font:11px Arial;fill:#333}`, and a docstring was left in place as a
warning — `generators/u1-vt-graphs.py:41-43`:

> "Authored in a 700-unit-wide viewBox so that, rendered at full column width,
> its labels come out the same visual size as the surrounding body text."

This is **realised-scale drift**: text inside an SVG is in viewBox units, so its
final rendered size depends on a ratio no stylesheet declares.

### Two further complaints in the aesthetic bucket

The spec files these as geometry, but their *symptom* was visual and their
detection was human, so they belong here.

**Complaint 3 — near-miss reflow.** §4.4 (`spec:111-117`):

> "Page 1 measured 936px against a 935px usable height. The only visible symptom
> was a single question appearing on the following page. There is no warning and
> no partial failure."

That single orphaned question is what a reader sees; 1px is what a checker sees.

**Complaint 4 — half-empty vs. crowded pages.** The goal statement (`spec:31`)
asks that "each page is close to full — deliberate-looking, not half-empty", but
§4.6 shows the naive fix overshooting 5→8 pages:

> "A pass that expanded writing space to fill short pages pushed every section
> slightly over the limit, taking the document from 5 pages to 8. Filling and
> fitting are the same constraint and must be solved together, not in sequence."

And §6.3 Q2 (`spec:249-251`) leaves it open whether "there is a comfort band
(say 88–96%) beyond which a page reads as crowded."

**Complaint 5 (latent, physics-specific).** §5.3 (`spec:170-173`):

> "graphs reading comfortably at 100% of their column width, aspect ratio capped
> near **2.3:1** — beyond that a stretched x–t graph misrepresents its slope,
> which for a physics document is a correctness problem, not a style one."

Note the framing: this is the one "aesthetic" check that is actually a
correctness gate, and it deserves hard-fail status.

### Complaint → measurable property

| # | Teacher's words | Underlying measurable property |
|---|---|---|
| 1 | "oversized graphs" | figure height as fraction of usable page height; height-source is `auto` |
| 2 | "supersized number line" | realised SVG text size ÷ body font size (scale-factor drift) |
| 3 | (orphaned question) | page overflow margin in px; `.qa` split across page boundary |
| 4 | "half-empty" / crowded | per-page ink fill ratio, outside a comfort band |
| 5 | (would-be) stretched graph | figure aspect ratio vs. profile cap — *correctness*, not style |

Everything else in §4 — measuring at the wrong width (§4.1), splice duplication
(§4.5), expand-then-overflow (§4.6) — is a process bug rather than an aesthetic
complaint. §4.5's guard (assert `<h2>` and `<svg>` counts; the session saw "8
instead of 6" and "23 instead of 14") is already correctly identified in the
spec as "**the highest-value guard in the document**." Build it first regardless
of anything else in this memo.

---

## A. Complaint → deterministic check map

Assume one canonical render:
`chrome --headless --no-pdf-header-footer --print-to-pdf` (the spec's known-good
technique, `spec:150-152`), plus one geometry pass via `--dump-dom` with an
injected script reading `getBoundingClientRect()` and `offsetTop`
(`spec:156-157`). Everything below reads from those two artifacts.

**Critically, all DOM geometry must be captured with the print stylesheet
active.** §4.1 is precisely the failure of measuring at screen width — "every
measurement was wrong and the resulting adjustments **moved in the wrong
direction**." Force print media by either (a) injecting a `<style>` that hoists
the `@media print` block into an unconditional rule before measuring, or (b)
driving CDP `Emulation.setEmulatedMedia({media:'print'})` followed by
`Runtime.evaluate`. Never trust a plain screen render again.

### A1. Oversized figures — deterministic

Two checks, one static and one measured.

**Static (source-level, free).** For every `svg`, resolve computed style and fail
if `height` resolves to `auto` while `width` is a percentage. §4.3's guard
verbatim: "Flag any `height:auto` figure as untunable until converted."

```js
getComputedStyle(el).height === 'auto' && /%/.test(el.style.width || cssWidth)  // FAIL
```

**Measured.** From the geometry pass:

```
h = el.getBoundingClientRect().height
FAIL if h / USABLE_PAGE_H > 0.28        // USABLE_PAGE_H = 935 (spec:169)
WARN if h / USABLE_PAGE_H > 0.22
```

0.28 ≈ 2.6in. The tuned values in the shipped diff sit at 1.45–2.55in
(0.14–0.25 of the page), so a 0.28 ceiling passes the shipped document, while
the 473px / 4.9in regression case scores 0.50 and fails with margin.

Set the ceiling per lever class once the knob manifest of §6.1 exists — `g-pa`
grids are small-multiples and should cap lower than `g-pc`, which is a solo
figure. A single global ceiling is the phase-1 approximation and is good enough
to catch the flagged regression.

### A2. Supersized SVG text — deterministic, and the highest-value new check

Fully computable; no judge needed. For each `<svg>`:

```
scale = svg.getBoundingClientRect().width / viewBoxWidth
for each <text> descendant t:
    realised_px = parseFloat(getComputedStyle(t).fontSize) * scale
ratio = realised_px / body_font_px          // body ≈ 14.7px per spec:105
```

Pass predicate, straight from §4.3's guard (`spec:107-109`) — "flag ratios
outside roughly 0.5×–0.9×":

```
FAIL if ratio > 0.95 or ratio < 0.45
WARN if ratio outside [0.55, 0.90]
```

Worked against both states of the number line:

- **Regression:** 7pt ≈ 9.33px, scale 700/210 = 3.33 → 31px realised;
  31 / 14.7 = **2.1×**. Fails by a factor of two.
- **Shipped fix:** `.nlk` is 10px in a 700-unit viewBox rendered ≈700px wide, so
  scale ≈ 1.0 → 10px realised; 10 / 14.7 = **0.68×**. Passes, comfortably inside
  the warn band.

This single predicate, computed at zero marginal cost during the geometry pass,
catches complaint 2 exactly and permanently.

**Cheaper source-only pre-flight (no render at all):** fail any figure whose
`viewBoxWidth` differs from its declared render width by more than 1.6×. That
catches 210-vs-700 statically, before a browser is ever launched.

### A3. Orphaned question / page overflow — deterministic

Two independent instruments; use both, because they fail differently.

**Slack per page (from geometry).** Sum block heights per page assignment:

```
slack_px = USABLE_PAGE_H - content_h
FAIL if slack_px < 0
FAIL if slack_px < TOL          // TOL = 12px, spec:116 says "≈10–15px"
```

§4.4's guard: "treat the page budget as `usable − tolerance` (≈10–15px). Never
target 100% fill. Report per-page slack so near-misses are visible." The
936-vs-935 case scores −1 and fails.

**Ground truth (from PDF).** `pdftotext -layout` piped through the form-feed
counter (`spec:153-155`) gives the section→page map. Assert:

1. page count equals the target;
2. each `<h2>` section's first and last text line share a page index;
3. for every `.qa` group, the prompt text and its answer-space marker land on
   the same page.

Assertions (2) and (3) are what page count alone cannot see — the spec is
explicit that "page count alone cannot" verify "each section starts its own
page."

**`.qa` splitting, checked in the DOM** (exact, and cheaper than text matching):

```js
const top = el.offsetTop, bot = top + el.offsetHeight;
const split = Math.floor(top / PAGE_H) !== Math.floor((bot - 1) / PAGE_H);  // → FAIL
```

### A4. Page fill / "half-empty vs. crowded" — semi-deterministic

Geometric fill (content height ÷ usable height) is deterministic and is the
right *gate*: fail below 0.80, warn above 0.99.

But geometric fill does not distinguish a page that is 94% full and beautifully
balanced from one that is 94% full with all its whitespace pooled in a single
corner. For that, use the ink-density measure in B1 as an advisory signal, and
escalate to a VLM only when the deterministic signals disagree (high fill *and*
high whitespace entropy).

Whether the comfort band is 88–96% is an **empirical question** to answer with
teacher labels (§C5), not a constant to assert now.

### A5. Aspect ratio — deterministic, hard gate

```
ar = rect.width / rect.height
FAIL if ar > 2.3 for any x–t or v–t grid          // spec:170-173
```

Hard-fail, not a warning, because the spec classifies it as "a correctness
problem, not a style one" — a stretched x–t graph misrepresents its slope. Bind
the cap to a figure role attribute (`data-fig-role="xt-graph"`) so the fitter
cannot quietly widen its way out of it.

### A6. What genuinely needs a VLM

Only three things, and be strict about the boundary — every check that can be
arithmetic should be arithmetic.

1. **Collisions and near-collisions between independently positioned things** —
   an axis label touching a border, a `.vlab` overlapping the figure below.
   Bounding-box intersection catches hard overlaps deterministically; it does
   *not* catch "technically 2px apart but reads as touching," and it produces
   false positives on nested and inline boxes. A VLM adjudicates the ambiguous
   residue, after the deterministic pass has already resolved the clear cases.

2. **"Does this page look deliberate?"** — the balance judgment behind
   "half-empty." No closed-form metric encodes it. The honest move is to reduce
   it to pairwise preference (B7/B8) rather than pretend a threshold exists.

3. **Semantic figure sizing** — "is this graph big enough for a student to
   *draw on*." §6.1 lists a "drawable minimum" as a soft constraint. The minimum
   in inches is deterministic once someone states it; whether a given figure is
   one students draw on is a content judgment. Solve it by **annotation**
   (`data-drawable="true"` emitted by the generator), not by vision — annotation
   converts a VLM question into an arithmetic one, and that trade is almost
   always worth making.

**Central finding.** Everything the teacher actually complained about in §4.7
falls under A1 and A2, and **both are fully deterministic**. The two flagged
aesthetic regressions were not aesthetic in any deep sense; they were unmeasured
ratios. A vision model was never required to catch them. A scale-factor
computation was.

---

## B. High-temperature ideas

Ordered roughly by ratio of insight to build cost.

**B1. Ink-density heatmap and whitespace entropy.**
Rasterize each PDF page at 100dpi (PyMuPDF `page.get_pixmap`), threshold to
binary ink, downsample to a 16×22 cell grid. Compute (a) fill fraction per cell,
(b) Shannon entropy of the normalized fill distribution, (c) center-of-mass
offset from page center. A page that is 90% full but bottom-heavy shows a COM
y-offset greater than 0.1·H — the fingerprint of "half-empty" that a scalar fill
ratio cannot see. Cheap, stable, no model, and the features feed straight into
B8.

**B2. Squint test.**
Gaussian-blur the page raster at σ ≈ 12px and compare the result to a golden
reference with SSIM. Blurring destroys glyph detail and preserves *mass
distribution* — exactly the level at which humans judge "looks wrong at arm's
length." A supersized number line survives a text diff and a naive geometry
check but changes the blurred page's mass profile dramatically. This is the
single best cheap proxy for the spec's "caught only by a human looking at the
page."

**B3. Perceptual differential rendering.**
Freeze the shipped 5-page worksheet as golden PNGs. On every change, render and
compute a per-page ΔE-based perceptual diff, and surface the diff image itself
in the report. This turns "did the fitter break something" into a picture the
teacher can approve in three seconds. Pair with B7 so the diff is scored, not
merely displayed.

**B4. Baseline-grid rhythm via FFT.**
Project ink onto the y-axis to obtain a 1-D density signal per page; take its
FFT. A well-set text block has a dominant peak at the line-height frequency;
figures and headings inject broadband noise. Measuring peak sharpness (spectral
flatness) yields a scalar "typographic rhythm" score, and — more usefully — the
*phase* tells you whether blocks following a figure have fallen off the baseline
grid. Novel, cheap, and it detects a whole class of vertical-rhythm ugliness
nothing currently checks.

**B5. Page as an explicit CSP; report violated constraints, not a score.**
Encode the §6.1 hard/soft constraints as a constraint set (`ortools` CP-SAT over
integer knob values in 1px units, using the additivity model of §3). Instead of
a pass/fail bit, emit the minimal *unsatisfiable core* — "no assignment exists
because Part B's figures at their legible minimum plus the required writing
space exceed one page." That is exactly the report line §7 asks for: "any
constraint that could not be satisfied." Far more actionable than a number, and
it directly answers §6.3 Q1: CP-SAT, not an LP, because page assignment is
integral.

**B6. Adversarial content generators.**
A property-based stress corpus: the longest plausible question text; a question
whose text lands exactly on a line-wrap boundary (the spec's one named
model-error source, `spec:72-73`); the tallest legal figure; a `.keep` block
that alone exceeds one page; a section with 40 short items. Generate with
Hypothesis over a content-shape grammar (n_questions, prose_len, n_figures,
figure_role). The fitter must either converge or *report* an unsatisfiable core
— silently producing 9 pages is a failure.

**B7. Pairwise VLM tournament with Bradley–Terry.**
Absolute VLM scores of layout quality are noisy and uncalibrated; pairwise
preferences are far more reliable. Render variant pages as images, have a VLM
judge A/B pairs (randomizing presentation order to cancel position bias), fit a
Bradley–Terry model over the comparison graph, and use the resulting latent
score as the soft objective term. Seed the graph with a handful of
teacher-judged pairs as anchors so the VLM's scale is tied to this user's actual
taste rather than to generic model preference.

**B8. Distill the teacher's judgments into a linear scorer over cheap features.**
The highest-leverage idea here. Collect ~60 teacher pairwise labels, featurize
each page with the deterministic quantities already computed (fill ratio,
whitespace entropy, COM offset, max figure height fraction, worst text-scale
ratio, min slack, aspect-ratio headroom, blur-SSIM to golden), and fit logistic
regression on feature *differences*. The result is an interpretable weight
vector — literally, how much this teacher trades figure size against page fill —
and a scorer costing microseconds instead of a VLM call. Run the VLM only where
the linear model sits near 0.5. This is how the loop stays fast as the corpus
grows.

**B9. Self-play: breaker vs. fitter.**
One agent proposes content or knob perturbations that maximize predicted
aesthetic loss under B8's scorer; the fitter must repair them. Any perturbation
that the deterministic gates *pass* but the teacher (or VLM) *rejects* is a new
gate to write — the loop mines its own blind spots. §4.7 is exactly one such
blind spot, found by hand; this finds the next one automatically.

**B10. Frozen regression corpus with per-page golden fingerprints.**
Store, per page: page count, section→page map, per-page slack, per-figure height
fraction and text-scale ratio, blur hash. Any change producing a delta beyond
tolerance requires an explicit accept, which rewrites the golden. Boring, and it
is what actually prevents recurrence.

**B11. Scale-factor lint as first-class static analysis.**
Generalize A2 into a standalone linter over any HTML: for every element inside a
scaled coordinate system (SVG viewBox, `transform: scale`, CSS zoom), compute
the realised px size of every text run and flag divergence from the document's
typographic scale. Applies to any physics worksheet, not just this one, and
would have caught complaint 2 without a browser at all.

**B12. Render at 4× and at 0.25× and compare structure.**
Legibility failures and scale-drift bugs show up as *inconsistency across zoom*:
correctly-authored content is affinely invariant under scaling; content whose
size derives from its container is not. A cheap invariance test that needs no
golden reference.

**B13. Simulated print degradation.**
Render grayscale at 300dpi, apply a mild dot-gain / blur model, and re-run the
legibility floor. The tinted `.key` and `.ans` blocks — which already require
`print-color-adjust: exact` to survive printing (`spec:166`) — are exactly where
screen-fine becomes paper-muddy. This checks the medium the artifact actually
ships to.

**B14. Reading-order as a rendered-geometry assertion, not a DOM one.**
§6.2 already specifies sorting leaf blocks by (page, top, left) and asserting
that reading indices are non-decreasing. Make it operate on *PDF text-block
coordinates* from pdfplumber rather than on DOM order — that catches CSS which
visually reorders content (flex `order`, floats, absolute positioning) and which
a DOM traversal will happily declare correct.

**B15. Eye-path plausibility.**
Compute a saliency-ordered traversal over the page raster and check that it
correlates with authored reading order. Speculative, but it operationalizes
"figures are large enough to read" as "the figure attracts attention in
proportion to its importance," and it degrades gracefully into B1's
center-of-mass metric if the saliency model disappoints.

---

## C. The iteration process

### C1. Search space

Three tiers, searched in this order — cheapest and most reversible first,
matching the spec's own lever priority (`spec:196-198`: "writing space →
figures → leading → structural moves").

1. **Knob values** (continuous, per-document): writing-space heights, figure
   heights, leading. Authored as `:root` custom properties per §6.1 step 1.
   Because of additivity (`spec:63-73`), this tier is searchable **without
   rendering** — solve it in arithmetic.

2. **CSS strategy variants** (discrete, ~8–15 total, shared across documents):
   height-driven vs. width-driven figures; `orphans`/`widows` 2 vs. 3; `.keep`
   granularity; explicit `break-before: page` per section vs. flowing on the
   avoid-rules alone; two-column parallel rows stacked vs. side-by-side;
   comfort-band target (88–96% vs. 98–99%).

3. **Prompt / profile variants** for whatever generates the HTML: how the
   generator is instructed to declare `data-fig-role`, `data-drawable`,
   `data-parallel-row`.

   §6.3 Q4 asks whether lever classes and minimums can be *inferred* from the
   document. My answer is **no, and don't try.** A `<span>` with a fixed height
   and no text is inferable; "students draw on this graph" is not, and a wrong
   inference is silent. Make the generator declare it — a one-line prompt change
   that converts three VLM questions into arithmetic.

Tier 1 is solved per document by the CP-SAT model (B5). Tiers 2 and 3 are
searched *across* the corpus, offline, and shipped as defaults. Do not confuse
the tiers — tuning tier 2 against a single document is exactly how you overfit.

### C2. Harness structure

```
corpus/<doc>/source.py|html
             profile.yaml         # page budget, figure roles, minimums
             golden/{page-N.png, fingerprint.json}
harness/
  render.py    -> pdf + page pngs + dom-geometry.json   (2 chrome invocations)
  checks/      -> one module per gate in §A, each returning
                  {id, severity, value, threshold, page, selector, message}
  features.py  -> the cheap feature vector for B8
  judge.py     -> VLM pairwise, cached by (image_hash_a, image_hash_b)
  score.py     -> objective assembly
  report.py    -> §7 report: per-page fill, knob deltas, structural moves
```

One render produces every artifact; every check reads artifacts, never the
browser. That keeps a full corpus evaluation at roughly (n_docs × 2s) and makes
checks unit-testable against frozen fixtures — you can write a test for A2 from
a saved `dom-geometry.json` containing the 3.33× number line and never launch
Chrome in CI.

### C3. Objective function

```
score = -inf                                    if any HARD gate fails
      = w_fill * fill_term
      + w_soft * Σ softmin(soft constraints)
      + w_pref * bradley_terry_score            (B7/B8)
```

**Hard gates** (`-inf`, no trade permitted):

- structural invariants unchanged (§4.5)
- page overflow with tolerance (A3)
- no `.qa` group split across a page (A3)
- reading order preserved (B14 / §6.2)
- aspect-ratio cap (A5)
- text-scale ratio outside [0.45, 0.95] (A2)

Note that A2 and A5 sit in the *hard* tier even though both arrived as
"aesthetic" complaints — both are now exactly computable, and both were real
ship-blockers.

**Soft terms:** fill within the comfort band; figure height vs. legible and
drawable minimums; whitespace entropy; center-of-mass balance.

Set `w_pref` low initially (≈0.15). The preference model is the least
trustworthy component, and the deterministic gates already cover both flagged
regressions. Letting a VLM outvote arithmetic is how you get plausible-looking
wrong answers.

**Answering §6.3 Q2** (*How should "fill the page" trade against "give more
writing room than strictly needed"? Is maximum fill even correct?*): No. Adopt a
comfort band and make 98–99% (the spec's current target, `spec:170`) a
**ceiling**, not a target. §4.4's 936-vs-935 failure is the natural consequence
of targeting maximum fill: at 99%, a one-pixel model error becomes a page break.
Target **92%** with a band of 88–96%, and treat the §5.3 constant as the hard
upper bound. Then measure whether the teacher agrees — the band is a hypothesis,
and C5 is how you test it.

**Answering §6.3 Q3** (*How large a prediction/measurement discrepancy should
trigger a full re-solve versus a local correction?*): The additivity model
predicts height exactly for fixed-height knobs; the only error source is prose
sitting near a line-wrap boundary (`spec:72-73`). Budget **±6px per section**.
Below that, apply a local correction to the largest-slack page and re-verify.
Above it, the model is wrong — do a full re-solve, and log the document as a
wrap-boundary risk. Cap at 4 iterations, per §5 step 5.

### C4. Avoiding corpus overfit

- **Split the corpus.** Tune tier-2 CSS strategy on a dev set (5–6 documents),
  and report on a held-out set the tuner never sees. With a corpus this small,
  use k-fold with k=5 and report the variance, not just the mean.
- **Property-based content, not just real documents** (B6). Real worksheets
  share an author's habits; generated content shapes do not. A strategy that
  wins on the dev set and loses on generated content is overfit, full stop.
- **Cap tier-2 selection pressure.** Prefer the simplest strategy within one
  standard error of the best (the 1-SE rule). Fifteen variants over six
  documents will produce a spurious winner if you take the argmax.
- **Never let the optimizer touch the gate thresholds.** Thresholds come from
  teacher labels and physics constraints; the fitter searches knobs and
  strategies only.

### C5. How many teacher labels

Fewer than you would guess, because the deterministic gates carry most of the
load.

- **Calibrating the comfort band:** ~20 pages rated on a 3-point scale (too
  empty / right / crowded), which fits one threshold pair with usable
  confidence. One sitting, about 15 minutes.
- **Fitting the linear preference model (B8):** ~60 pairwise comparisons over 8
  features (rule of thumb: 8–10 comparisons per feature). Collect them as
  forced-choice A/B on rendered page images — pairwise judgments are far less
  fatiguing and far more reliable than absolute ratings.
- **Anchoring the VLM judge:** hold out ~20 of those 60 as agreement checks. If
  VLM–teacher agreement falls below ~75%, set `w_pref` to 0 and ship on
  deterministic gates alone. That is a perfectly good outcome, and probably
  where you land initially.

Total ≈ 80 judgments, roughly one hour of the teacher's time, with ~15 more
collected per quarter as the corpus grows.

### C6. Gating a change from "passes checks" to "shipped"

1. All hard gates pass on the changed document.
2. No regression on the frozen corpus: no document's page count changes, no gate
   flips pass→fail, no per-page slack drops below tolerance.
3. Blur-SSIM against golden ≥ 0.97, or an explicit accept that rewrites the
   golden with a one-line reason.
4. The §7 report renders: per-page fill, every knob old→new, every structural
   move by name, and any constraint that could not be satisfied.
5. **The teacher sees page images for any document whose blur-SSIM moved by more
   than 0.02.** This honors §4.7's guard — "a mandatory visual review pass on
   rendered page images before reporting success" — but gates it on the diff, so
   it is not required on every run. This is the concession that keeps a human in
   an otherwise-automatic loop without making the human the bottleneck.

### C7. Phased build order — the cheap 20% that catches 80%

**Phase 0 (half a day; do this before anything else).**
Structural invariants: assert counts of `<h2>`, `<svg>`, `.qa`, and total
visible text length before and after every automated edit; abort and restore on
mismatch. §4.5 calls this "the highest-value guard in the document," and it is
the one failure that silently *corrupts content* rather than merely looking
wrong — the session shipped 8 `<h2>` instead of 6 and 23 `<svg>` instead of 14,
and the document rendered without error.

**Phase 1 (one to two days — catches both flagged aesthetic regressions).**

- Force print media for all geometry capture. This kills §4.1, which had made
  every other measurement meaningless.
- A2 text-scale ratio check → catches "supersized number line" exactly.
- A1 figure-height-fraction check + `height:auto` lint → catches "oversized
  graphs" exactly.
- A3 per-page slack with 12px tolerance + `.qa`-split detection → catches the
  orphaned question.
- A5 aspect-ratio hard cap.
- Freeze the current 5-page worksheet and its answer key as the golden corpus,
  with a fingerprint JSON.

That is the 20%. Every complaint in §4.7 — and the two §4 root causes behind
them — is caught by four arithmetic predicates over one geometry pass. No vision
model, no learned scorer, no labels.

**Phase 2 (a few days).**
Knob manifest plus CP-SAT solve with unsatisfiable-core reporting (B5); the §7
report; blur-SSIM against golden (B2); ink-density / entropy / center-of-mass
features (B1). This is the phase where the loop actually converges in ≤3 renders
as §7 requires.

**Phase 3.**
Teacher labels → comfort band plus the linear preference model (B8). VLM as
tiebreaker only (B7). Adversarial content generator (B6).

**Phase 4 (only if phases 1–3 leave real gaps).**
Self-play breaker (B9), baseline-grid FFT (B4), print-degradation simulation
(B13), eye-path plausibility (B15).

### C8. Two spec questions I would close now

**§6.3 Q1 — LP or MIP?**
CP-SAT over integer pixel knobs. The page assignment is genuinely integral, and
the problem is tiny (tens of knobs, single-digit pages) — CP-SAT solves it in
milliseconds and, unlike a greedy search, hands you the unsatisfiable core when
it cannot. Greedy search plus verification is precisely the thing that
oscillated in the source session.

**§6.3 Q5 — worksheet and answer-key coherence?**
Fit the **worksheet only**; let the key flow. The generator already produces both
from one source (`build(KEY)` in
`generators/u1-vt-graphs.py`), and the
code comments note that the key "is longer, so it flows on the avoid-rules
alone." Joint fitting would force the worksheet's writing space to shrink in
order to accommodate the key's answer prose — optimizing the student artifact
against a constraint the student never sees. Run the hard gates on both
documents; run the fill objective on the worksheet only.

---

## Bottom line

The teacher's "aesthetic regression" was not a taste problem. Both flagged items
were quantities nobody was measuring: a figure whose height derived from its
container, and SVG text whose size derived from an undeclared viewBox ratio.
Four arithmetic checks over one print-media geometry pass catch every complaint
in the log.

Build those, freeze a golden corpus, and treat the VLM and preference machinery
as phase 3 — it is where the interesting ideas live, but it is not where the
flagged bugs were.
