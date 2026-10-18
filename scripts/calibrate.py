"""Calibration for the soft visual gates (spec Part 4).

  uv run python scripts/calibrate.py collect [ROOT ...] [--reports DIR]
  uv run python scripts/calibrate.py rescore LABELS.json

collect renders every printable document once, stores its artifacts,
runs duplicate_content, label_collision and arrow_shaft, and writes
out/calibration/review.html: one card per sampled finding with a zoomed crop,
the finding, and Real / False alarm buttons. "Copy results" puts the labels
on the clipboard as JSON. rescore re-runs the gates on stored geometry, so
tolerances can be tuned without re-rendering.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import os
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw

from printfit import profile as P
from printfit import render as R
from printfit.checks import arrow_shaft, duplicate, label_collision

OUT = Path("out/calibration")
PRINTFIT_OUT = "~/projects/printfit/out"
BUILDER_DIRS = ("~/projects/knowledge-base/scripts",)
DEFAULT_ROOT = "~/projects/knowledge-base/curriculum"
KEY_RX = re.compile(r"(^|[^a-z])key([^a-z]|$)|answer-key|key-variant", re.I)
SOLUTION_RX = re.compile(r"(^|[^a-z])solutions?([^a-z]|$)", re.I)
GENERIC_NAMES = {"index.html", "homework.html", "worksheet.html", "quiz.html", "test.html", "notes.html"}
SKIP_PARTS = ("/printfit/out/", "/node_modules/", "/site/", "/scratchpad/")
SAMPLE = 60
PAD_PX = 24
ARROW_PAD_PX = 12
SCALE = 2
ARROW_SCALE = 4
CAPTIONS = {"label_collision": "Red: the flagged label. Blue: what it overlaps.",
            "arrow_shaft": "Red: the arrowhead. Blue: the shaft."}
FALSE_PER_20 = 1          # promotion bar for the geometry gates
GEOMETRY_GATES = {"label_collision": label_collision, "arrow_shaft": arrow_shaft}


def _skipped(p: Path) -> bool:
    return (any(x in str(p) or x in str(p.resolve()) for x in SKIP_PARTS) or bool(KEY_RX.search(p.name))
            or p.name.startswith("_") or any(SOLUTION_RX.search(part) for part in p.parts))


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8", errors="ignore") if p.is_file() else None
    except OSError:
        return None


def _builder_targets(roots, builder_dirs) -> set[str]:
    """HTML paths named by builder scripts: bare basenames, folder/basename pairs, and dir:basename."""
    names: set[str] = set()
    for root in [*roots, *builder_dirs]:
        for py in Path(root).expanduser().rglob("*.py"):
            if any(x in str(py) for x in SKIP_PARTS) or "/.venv/" in str(py):
                continue
            text = _read(py)
            for m in re.findall(r"[\w./~-]+\.html", text or ""):
                parts = Path(m).parts
                names |= {parts[-1], f"{py.parent.resolve()}:{parts[-1]}"}
                if len(parts) > 1:
                    names.add("/".join(parts[-2:]))
    return names


def _is_built(p: Path, built: set[str]) -> bool:
    # A generic basename counts only from a script in its own dir or one naming folder/basename.
    return ((p.name not in GENERIC_NAMES and p.name in built) or f"{p.parent.name}/{p.name}" in built
            or f"{p.parent.resolve()}:{p.name}" in built)


def _reported_docs(reports) -> list[Path]:
    docs = []
    for rj in sorted(Path(reports).expanduser().glob("*/report.json")):
        try:
            doc = json.loads(rj.read_text()).get("doc")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(doc, dict):
            doc = doc.get("path")
        if isinstance(doc, str) and doc:
            p = Path(doc).expanduser()
            if p.suffix == ".html" and p.is_file() and not _skipped(p):
                docs.append(p)
    return docs


def corpus(roots, reports=PRINTFIT_OUT, builder_dirs=BUILDER_DIRS):
    """Printables with an SVG or a builder script, plus the hook's reported sources."""
    built = _builder_targets(roots, builder_dirs)
    found: dict[Path, Path] = {}
    for root in roots:
        for p in Path(root).expanduser().rglob("*.html"):
            if _skipped(p):
                continue
            text = _read(p)
            if text and re.search(r"@page|@media print", text) and ("<svg" in text or _is_built(p, built)):
                found.setdefault(p.resolve(), p)
    for p in _reported_docs(reports):
        found.setdefault(p.resolve(), p)
    for key in sorted(found):
        yield found[key]


def slug(p: Path) -> str:
    return hashlib.sha1(str(Path(p).resolve()).encode()).hexdigest()[:10] + "-" + Path(p).stem


def sample(items: list[dict]) -> list[dict]:
    by = defaultdict(list)
    for it in items:
        by[it["gate"]].append(it)
    rng = random.Random(0)
    out = []
    for gate in sorted(by):
        xs = by[gate]
        out += rng.sample(xs, SAMPLE) if len(xs) > SAMPLE else xs
    return out


def region(polys, page_w: float, pad: float = PAD_PX) -> tuple[float, float, float, float]:
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    return (max(0.0, min(xs) - pad), max(0.0, min(ys) - pad),
            min(page_w, max(xs) + pad), max(ys) + pad)


def crop_spec(it: dict, page_w: float):
    """(region, scale) for a finding's crop: arrow_shaft zooms on the head only."""
    if it["gate"] == "arrow_shaft":
        return region(it["polys"][:1], page_w, ARROW_PAD_PX), ARROW_SCALE
    return region(it["polys"], page_w), SCALE


def shoot(html_path: str, content_w: float, regions, scale: float = SCALE) -> list[bytes]:
    cdp = R._CDP(R.find_chrome())
    try:
        cdp.send("Page.enable")
        cdp.send("Emulation.setEmulatedMedia", media="print")
        cdp.send("Page.navigate", url="file://" + os.path.abspath(html_path))
        cdp.wait_event("Page.loadEventFired")
        cdp.send("Emulation.setDeviceMetricsOverride", width=int(round(content_w)), height=1000,
                 deviceScaleFactor=1, mobile=False)
        cdp.evaluate("document.fonts.ready.then(()=>true)", await_promise=True)
        out = []
        for x0, y0, x1, y1 in regions:
            r = cdp.send("Page.captureScreenshot", format="png", captureBeyondViewport=True,
                         clip={"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0, "scale": scale})
            out.append(base64.b64decode(r["data"]))
        return out
    finally:
        cdp.close()


def outline(png: bytes, polys, origin, scale: float = SCALE) -> str:
    im = Image.open(io.BytesIO(png)).convert("RGB")
    dr = ImageDraw.Draw(im)
    for poly, color in zip(polys, ("#d0342c", "#1f6feb")):
        pts = [((x - origin[0]) * scale, (y - origin[1]) * scale) for x, y in poly]
        dr.polygon(pts, outline=color, width=2)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def review_html(items: list[dict]) -> str:
    keys = sorted(f"{it['slug']}|{it['fid']}" for it in items)
    store = "calibrate-labels-" + hashlib.sha1("\n".join(keys).encode()).hexdigest()[:12]
    cards = []
    for it in items:
        key = html.escape(f"{it['slug']}|{it['fid']}")
        img = f'<img src="data:image/png;base64,{it["png"]}" alt="">' if it.get("png") else ""
        cap = CAPTIONS.get(it["gate"]) if it.get("png") else None
        legend = f'<p class="legend">{html.escape(cap)}</p>' if cap else ""
        cards.append(
            f'<section class="card"><h3>{html.escape(it["gate"])}</h3>'
            f'<p class="doc">{html.escape(it["doc"])}</p>{img}{legend}'
            f'<p>{html.escape(it["message"])}</p><p class="fix">{html.escape(it.get("fix") or "")}</p>'
            f'<label><input type="radio" name="{key}" value="real"> Real</label> '
            f'<label><input type="radio" name="{key}" value="false"> False alarm</label></section>')
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Gate calibration</title>
<style>
:root {{ --bg:#fff; --fg:#1b1b1b; --muted:#666; --line:#ddd; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161616; --fg:#eee; --muted:#aaa; --line:#333; }} }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.45 system-ui, sans-serif; max-width:960px; margin:0 auto; padding:16px; }}
.card {{ border-bottom:1px solid var(--line); padding:16px 0; }}
.card img {{ max-width:100%; border:1px solid var(--line); background:#fff; }}
.doc, .fix, .legend {{ color:var(--muted); font-size:13px; }}
#bar {{ position:sticky; top:0; background:var(--bg); padding:8px 0; border-bottom:1px solid var(--line); }}
textarea {{ width:100%; height:6em; }}
</style></head><body>
<div id="bar"><button id="copy">Copy results</button> <span id="n"></span>
<textarea id="out" readonly placeholder="Labels appear here if the clipboard is blocked"></textarea></div>
<p>{len(items)} findings.</p>
{''.join(cards)}
<script>
const STORE = {json.dumps(store)};
const out = document.getElementById('out'), n = document.getElementById('n');
const radios = () => document.querySelectorAll('input[type=radio]');
function labels() {{
  const r = {{}};
  document.querySelectorAll('input[type=radio]:checked').forEach(i => r[i.name] = i.value);
  return r;
}}
function refresh() {{
  const r = labels();
  out.value = JSON.stringify(r, null, 1);
  n.textContent = Object.keys(r).length + ' labels';
  return r;
}}
try {{
  const saved = JSON.parse(localStorage.getItem(STORE) || '{{}}');
  radios().forEach(i => {{ if (saved[i.name] === i.value) i.checked = true; }});
}} catch (e) {{}}
refresh();
document.addEventListener('change', e => {{
  if (e.target.type !== 'radio') return;
  const r = refresh();
  try {{ localStorage.setItem(STORE, JSON.stringify(r)); }} catch (e) {{}}
}});
document.getElementById('copy').onclick = () => {{
  const s = JSON.stringify(refresh(), null, 1);
  try {{ navigator.clipboard.writeText(s).catch(() => {{}}); }} catch (e) {{}}
}};
</script></body></html>"""


def collect(roots, reports=PRINTFIT_OUT) -> int:
    prof = P.load(None)
    OUT.mkdir(parents=True, exist_ok=True)
    items, widths = [], {}
    docs = list(corpus(roots, reports))
    print(f"corpus: {len(docs)} documents")
    for p in docs:
        sl = slug(p)
        d = OUT / sl
        try:
            art = R.render(str(p), str(d))
        except Exception as e:  # one bad document must not stop the corpus
            print(f"skip {p}: {e}", file=sys.stderr)
            continue
        R.save_artifacts(art, str(d / "artifacts.json"))
        widths[str(p)] = art.page_content_w_px
        for gate, mod in GEOMETRY_GATES.items():
            for h in mod.hits(art, prof):
                items.append({"gate": gate, "doc": str(p), "slug": sl, **h})
        for f in duplicate.run_html(str(p)):
            items.append({"gate": "duplicate_content", "doc": str(p), "slug": sl, "fid": f.id,
                          "message": f.message, "fix": f.suggested_fix})
        print(f"{sl}: {sum(1 for i in items if i['slug'] == sl)} findings")
    (OUT / "hits.json").write_text(json.dumps(items, indent=1, default=list))
    chosen = sample(items)
    by_doc = defaultdict(list)
    for it in chosen:
        if it.get("polys"):
            by_doc[it["doc"]].append(it)
    for doc, its in by_doc.items():
        specs = [crop_spec(it, widths[doc]) for it in its]
        for scale in sorted({sc for _, sc in specs}):
            group = [(it, reg) for it, (reg, sc) in zip(its, specs) if sc == scale]
            pngs = shoot(doc, widths[doc], [reg for _, reg in group], scale)
            for (it, reg), png in zip(group, pngs):
                it["png"] = outline(png, it["polys"], reg[:2], scale)
    (OUT / "review.html").write_text(review_html(chosen), encoding="utf-8")
    print(f"{len(items)} findings, {len(chosen)} sampled -> {OUT / 'review.html'}")
    return 0


def dup_meets_bar(s: dict) -> bool:
    """duplicate_content passes only with at least one label and no misses or false flags."""
    return s["real"] + s["false"] > 0 and s["real_caught"] == s["real"] and s["false_flagged"] == 0


def score(labels: dict, found: set) -> dict:
    real = {k for k, v in labels.items() if v == "real"}
    false = {k for k, v in labels.items() if v == "false"}
    rc, ff = len(real & found), len(false & found)
    flagged = rc + ff
    meets = rc == len(real) and flagged > 0 and ff * 20 <= FALSE_PER_20 * flagged
    return {"real": len(real), "real_caught": rc, "false": len(false), "false_flagged": ff,
            "meets_bar": meets}


def rescore(labels_path: str) -> int:
    labels = json.loads(Path(labels_path).read_text())
    prof = P.load(None)
    found: dict[str, set] = defaultdict(set)
    docs = {it["slug"]: it["doc"] for it in json.loads((OUT / "hits.json").read_text())}
    for d in sorted(p for p in OUT.iterdir() if (p / "artifacts.json").exists()):
        art = R.load_artifacts(str(d / "artifacts.json"))
        for gate, mod in GEOMETRY_GATES.items():
            found[gate] |= {f"{d.name}|{h['fid']}" for h in mod.hits(art, prof)}
    for sl, doc in docs.items():
        if Path(doc).exists():
            found["duplicate_content"] |= {f"{sl}|{f.id}" for f in duplicate.run_html(doc)}
    for gate in ("duplicate_content", "label_collision", "arrow_shaft"):
        mine = {k: v for k, v in labels.items() if k.split("|", 1)[1].startswith(gate + ":")}
        s = score(mine, found[gate])
        if gate == "duplicate_content":
            s["meets_bar"] = dup_meets_bar(s)
        print(f"{gate:18} {s}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("roots", nargs="*", default=[DEFAULT_ROOT])
    c.add_argument("--reports", default=PRINTFIT_OUT)
    r = sub.add_parser("rescore")
    r.add_argument("labels")
    a = ap.parse_args(argv)
    return collect(a.roots, a.reports) if a.cmd == "collect" else rescore(a.labels)


if __name__ == "__main__":
    sys.exit(main())
