"""Generate the synthetic "stuck" test fixture (t2-stuck.html).

Failure shape: a short intro leaves page 1 mostly empty because "Part I"
(h2 inside div.mcblock, a break-inside:avoid group) is too tall to fit
after it and moves whole to page 2.

Run from the repo root: uv run python tests/fixtures/t2-stuck/make_stuck.py
Then regenerate geometry.json / report.json (see README note in the commit).
"""
from pathlib import Path

HERE = Path(__file__).parent

CSS = """:root{--ink:#111;--mut:#555;--rule:#bbb;--band:#f2f2f2}
*{box-sizing:border-box}
body{font:11pt/1.42 sans-serif;color:var(--ink);max-width:7.6in;margin:0 auto;padding:.35in .4in;background:#fff}
h1{font-size:15pt;margin:0 0 2px}
h2{font-size:11.5pt;margin:14px 0 6px;padding:3px 7px;background:var(--band);border-left:3px solid #333}
.sub{color:var(--mut);font-size:9.5pt;margin:0 0 10px}
.name{border-bottom:1px solid var(--ink);display:inline-block;min-width:2.6in}
.hdr{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid var(--ink);padding-bottom:6px;margin-bottom:10px}
.rubric{border:1px solid var(--rule);padding:7px 10px;font-size:9.5pt;margin:0 0 12px;background:#fafafa}
.q{margin:7px 0}
.sp{display:block;background:#fff}
.opts{list-style:none;margin:4px 0 0 18px;padding:0;font-size:10.5pt}
.opts li{margin:3px 0}
.mcq{page-break-inside:avoid;margin-bottom:9px}
.mcblock{break-inside:avoid;page-break-inside:avoid}
h2{break-after:avoid;page-break-after:avoid}
.prob{page-break-inside:avoid;margin-bottom:14px}
@page{margin:.45in;size:letter}
"""


def mcq(n: int) -> str:
    opts = "".join(f'<li>{c}. Choice {c} for question {n}.</li>' for c in "ABCD")
    return (f'<div class="mcq"><p class="q"><b>{n}.</b> A cart moves along a track in situation {n}. '
            f'Which statement about its velocity is correct?</p><ul class="opts">{opts}</ul></div>')


def prob(n: int) -> str:
    return (f'<div class="prob"><p class="q"><b>{n}.</b> A cart starts from rest and speeds up at a constant rate. '
            f'Find its velocity after 4.0 s and the distance it covers.</p>'
            f'<div class="sp" style="height:2.4in"></div></div>')


def build() -> str:
    h = ['<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">',
         "<title>Motion Test</title>", f"<style>{CSS}</style></head><body>",
         '<div class="hdr"><div><h1>Motion Test</h1><p class="sub">Physics</p></div>'
         '<div style="font-size:10pt">Name <span class="name"></span></div></div>',
         '<div class="rubric"><b>Before you start.</b> Show the equation you start from, rearrange it for the '
         'unknown, and only then substitute numbers.</div>',
         '<div class="mcblock"><h2>Part I &mdash; Multiple Choice</h2>']
    h += [mcq(n) for n in range(1, 9)]
    h.append("</div>")
    h.append("<h2>Part II &mdash; Long Answer</h2>")
    h += [prob(n) for n in range(9, 12)]
    h.append("</body></html>")
    return "\n".join(h) + "\n"


if __name__ == "__main__":
    (HERE / "t2-stuck.html").write_text(build())
