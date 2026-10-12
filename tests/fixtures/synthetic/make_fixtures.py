"""Generate the synthetic worksheet fixtures used by the test suite.

Run from the repo root:  uv run python tests/fixtures/synthetic/make_fixtures.py

Writes two generic physics worksheets next to this script:
  fixed-worksheet.html   figures sized in CSS, text scale in band (passes)
  prefix-worksheet.html  same content, figures left at width:100%/height:auto
                         (the classic regressions: height derives from the column, and
                         text in a narrow viewBox renders far too large)
"""
from pathlib import Path

HERE = Path(__file__).parent

CSS_COMMON = """:root{--ink:#111;--mut:#555;--rule:#bbb;--band:#f2f2f2;--acc:#1a5c3a;}
*{box-sizing:border-box}
body{font:11pt/1.45 sans-serif;color:var(--ink);max-width:7.6in;margin:0 auto;padding:.35in .4in;background:#fff}
h1{font-size:15pt;margin:0 0 2px}
h2{font-size:11.5pt;margin:16px 0 6px;padding:3px 7px;background:var(--band);border-left:3px solid #333;text-transform:uppercase;letter-spacing:.04em}
.sub{color:var(--mut);font-size:9.5pt;margin:0 0 10px}
.name{border-bottom:1px solid var(--ink);display:inline-block;min-width:2.6in}
.hdr{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid var(--ink);padding-bottom:6px;margin-bottom:10px}
.key{border:1.5px solid #333;padding:8px 11px;margin:10px 0;background:#fafafa}
.key b.lbl{display:block;font-size:9pt;letter-spacing:.06em;text-transform:uppercase;color:#333;margin-bottom:3px}
.eq{text-align:center;font-size:12pt;margin:6px 0}
.row{display:flex;gap:12px;align-items:flex-start;margin:8px 0}
.col{flex:1}
.nlk{font:10px Arial;fill:#333}
.nla{font:11px Arial;fill:#333}
.gl{stroke:#dcdcdc;stroke-width:.5}
.ax{stroke:#222;stroke-width:1.2}
.pl{stroke:#1a1a1a;stroke-width:2.2;stroke-linecap:round}
.al{font:8pt Arial;fill:#333}
.tk{font:7pt Arial;fill:#555}
.q{margin:7px 0}
.sp{display:block;background:#fff}
.tag{font-size:8.5pt;color:var(--mut);float:right;font-weight:400}
table{border-collapse:collapse;width:100%;font-size:10pt;margin:6px 0}
th,td{border:1px solid #999;padding:3px 6px;text-align:center}
th{background:var(--band);font-size:9pt}
"""

CSS_FIXED = """svg.grid{display:block;width:auto;height:1.45in;max-width:100%;margin:0 auto;border:1px solid var(--rule);background:#fff}
svg.g-warm{height:1.6in}
svg.g-pa{height:1.46in}
svg.g-pb{height:2.37in}
svg.g-pc{height:2.55in}
svg.g-nl{width:100%;height:auto;border:1px solid var(--rule)}
"""

CSS_PREFIX = """svg.grid{width:100%;height:auto;border:1px solid var(--rule);background:#fff}
"""

CSS_PRINT = """@media print{
  body{padding:.18in .25in;max-width:7.3in}
  h2{background:#eee !important;-webkit-print-color-adjust:exact}
  .qa{break-inside:avoid;page-break-inside:avoid}
  .row{break-inside:avoid;page-break-inside:avoid}
  .key{break-inside:avoid;page-break-inside:avoid}
  table{break-inside:avoid;page-break-inside:avoid}
  svg.grid{break-inside:avoid;page-break-inside:avoid}
  h2{break-after:avoid;page-break-after:avoid}
  .pb{break-before:page;page-break-before:always}
}
@page{margin:.45in;size:letter}
"""


def grid(cls: str, slope: float, w: int = 310, h: int = 152) -> str:
    """An x-t style graph: 6 x 6 gridlines, tick labels, axis labels, one line."""
    x0, x1, y0, y1 = 34.0, w - 10.0, 10.0, h - 28.0
    out = [f'<svg viewBox="0 0 {w} {h}" class="grid {cls}">']
    for i in range(7):
        x = x0 + (x1 - x0) * i / 6
        y = y1 - (y1 - y0) * i / 6
        out.append(f'<line x1="{x:.1f}" y1="{y0}" x2="{x:.1f}" y2="{y1}" class="gl"/>')
        out.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" class="gl"/>')
        out.append(f'<text x="{x0 - 4}" y="{y + 2.4:.1f}" class="tk" text-anchor="end">{i}</text>')
        out.append(f'<text x="{x:.1f}" y="{y1 + 9}" class="tk" text-anchor="middle">{i}</text>')
    out.append(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" class="ax"/>')
    out.append(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" class="ax"/>')
    out.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{h - 4}" class="al" text-anchor="middle">time t (s)</text>')
    out.append(f'<text x="9" y="{(y0 + y1) / 2:.1f}" class="al" text-anchor="middle" '
               f'transform="rotate(-90 9 {(y0 + y1) / 2:.1f})">position x (m)</text>')
    ye = max(y0, y1 - slope * (y1 - y0))
    out.append(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{ye:.1f}" class="pl"/>')
    out.append("</svg>")
    return "".join(out)


def numberline(w: int, h: int) -> str:
    """A scale: a number line with tick labels (role "scale")."""
    mid = h * 0.45
    out = [f'<svg viewBox="0 0 {w} {h}" class="grid g-nl">']
    out.append(f'<line x1="14" y1="{mid}" x2="{w - 14}" y2="{mid}" class="ax"/>')
    for i in range(11):
        x = 14 + (w - 28) * i / 10
        out.append(f'<line x1="{x:.1f}" y1="{mid - 5}" x2="{x:.1f}" y2="{mid + 5}" class="ax"/>')
        out.append(f'<text x="{x:.1f}" y="{mid + 17}" class="nlk" text-anchor="middle">{i * 2 - 10}</text>')
    out.append(f'<text x="{w / 2}" y="{h - 4}" class="nla" text-anchor="middle">velocity v (m/s)</text>')
    out.append("</svg>")
    return "".join(out)


def sp(inches: float) -> str:
    return f'<div class="sp" style="height:{inches}in"></div>'


def qa(text: str, space: float) -> str:
    return f'<div class="qa"><p class="q">{text}</p>{sp(space)}</div>'


def build(fixed: bool) -> str:
    nl = numberline(700, 90)
    h = ["<title>Motion Graphs Practice</title>", "<style>", CSS_COMMON,
         CSS_FIXED if fixed else CSS_PREFIX, CSS_PRINT, "</style>"]
    h.append('<div class="hdr"><div><h1>Motion Graphs Practice</h1>'
             '<p class="sub">Physics &mdash; position-time and velocity-time graphs</p></div>'
             '<div style="font-size:10pt">Name <span class="name"></span></div></div>')

    h.append('<h2>Warm-up <span class="tag">5 min</span></h2>')
    h.append('<div class="qa"><p class="q">A cart rolls along a track. Its position data are plotted below.</p>'
             + grid("g-warm", 0.5) + sp(0.9) + "</div>")
    h.append('<h2>The idea <span class="tag">10 min</span></h2>')
    h.append('<div class="key"><b class="lbl">Two graphs, one motion</b>'
             '<div class="eq">slope of an <i>x&ndash;t</i> graph = velocity</div>'
             '<p>The slope is rise over run, with units of meters per second.</p></div>')
    h.append(qa("Explain in one sentence what a steeper <i>x&ndash;t</i> line tells you about the motion.", 0.7))

    h.append('<h2 class="pb">Part A &mdash; read the slope <span class="tag">10 min</span></h2>')
    h.append('<p class="q">Use each scale to calculate the slope and write the velocity with its sign and units.</p>')
    slopes = [0.9, 0.6, 0.4, 0.75, 0.3, 0.55, 0.85, 0.2]
    for r in range(4):
        h.append('<div class="row pa" style="align-items:center;margin:5px 0">')
        for c in range(2):
            h.append(f'<div class="col" style="flex:0 0 46%">{grid("g-pa", slopes[r * 2 + c])}'
                     f'<div class="sp" style="height:0.45in"></div></div>')
        h.append("</div>")

    h.append('<h2 class="pb">Part B &mdash; compare two motions <span class="tag">8 min</span></h2>')
    for k, s in enumerate((0.8, 0.35)):
        h.append('<div class="qa"><p class="q">Graph %d shows one cart. Find its velocity and say how far it moves in 6 s.</p>' % (k + 1)
                 + grid("g-pb", s, 310, 230) + sp(0.9) + "</div>")

    h.append('<h2 class="pb">Part C &mdash; sketch the second graph <span class="tag">10 min</span></h2>')
    for k, s in enumerate((0.7, 0.45)):
        h.append('<div class="qa"><p class="q">Sketch the matching <i>v&ndash;t</i> graph for motion %d.</p>' % (k + 1)
                 + grid("g-pc", s, 250, 270) + sp(0.7) + "</div>")

    h.append('<h2 class="pb">Part D &mdash; reading a scale <span class="tag">8 min</span></h2>')
    h.append('<div class="qa"><p class="q">Mark the velocities 4 m/s and &minus;6 m/s on the number line.</p>'
             + nl + sp(0.6) + "</div>")
    h.append("<table><tr><th>Interval</th><th>Displacement (m)</th><th>Velocity (m/s)</th></tr>"
             "<tr><td>0 to 2 s</td><td></td><td></td></tr><tr><td>2 to 4 s</td><td></td><td></td></tr></table>")
    h.append(qa("Which interval had the larger speed? State how you know from the table.", 0.8))
    h.append(qa("State whether the cart in the table was speeding up or slowing down, and how you can tell.", 0.8))
    h.append(qa("A second cart moves with the same speed but in the opposite direction. "
                "Describe how its <i>x&ndash;t</i> line differs.", 0.9))
    return "\n".join(h) + "\n"


if __name__ == "__main__":
    (HERE / "fixed-worksheet.html").write_text(build(True))
    (HERE / "prefix-worksheet.html").write_text(build(False))
