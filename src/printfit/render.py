"""The single render pass. One Chrome, one page lifetime, over CDP; then
nothing else touches a browser.

The non-negotiable detail: geometry must be captured with the *print*
stylesheet active. Measuring at screen width was the original failure that
made every other measurement in the source session meaningless (spec 4.1).
Forced via CDP `Emulation.setEmulatedMedia({media: "print"})` and a device
width equal to the page content width, before any `Runtime.evaluate`.
"""
from __future__ import annotations

import base64
import dataclasses
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import pdfplumber
import pymupdf
import websocket

from .types import HarnessError, PageMetrics, RenderArtifacts

PT = 96 / 72
CHROME_DEFAULT_MARGIN_PX = 96 / 2.54          # CDP printToPDF default: 1cm
LETTER_W_PX, LETTER_H_PX = 816.0, 1056.0
A4_W_PX, A4_H_PX = 793.7, 1122.5

GEOMETRY_JS = r"""
(() => {
  const px = v => parseFloat(v) || 0;
  const cs = el => getComputedStyle(el);
  const sel = (el, i, counts) => {
    const cls = [...el.classList].map(c => '.' + c).join('');
    const key = el.tagName.toLowerCase() + cls;
    counts[key] = (counts[key] || 0) + 1;
    return counts[key] > 1 ? `${key}[${counts[key]}]` : key;
  };
  const sy = scrollY, sx = scrollX;
  const rectOf = el => { const r = el.getBoundingClientRect();
    return {x: r.left + sx, y: r.top + sy, w: r.width, h: r.height}; };

  // declared height from the matched cascade (not computed px)
  const rulesFor = (el, prop) => {
    let val = null;
    const walk = rules => { for (const r of rules) {
      if (r.type === CSSRule.MEDIA_RULE || r.type === CSSRule.SUPPORTS_RULE) {
        if (r.type !== CSSRule.MEDIA_RULE || matchMedia(r.media.mediaText).matches) walk(r.cssRules);
      } else if (r.type === CSSRule.STYLE_RULE) {
        const v = r.style.getPropertyValue(prop);
        if (v) { try { if (el.matches(r.selectorText)) val = v; } catch (e) {} }
      } } };
    for (const s of document.styleSheets) { try { walk(s.cssRules); } catch (e) {} }
    const inl = el.style.getPropertyValue(prop); if (inl) val = inl;
    return val;
  };
  let pageRule = null;
  for (const s of document.styleSheets) { try { for (const r of s.cssRules) {
    if (r.type === CSSRule.PAGE_RULE) pageRule = {
      marginTop: r.style.marginTop, marginRight: r.style.marginRight,
      marginBottom: r.style.marginBottom, marginLeft: r.style.marginLeft,
      margin: r.style.margin, size: r.style.getPropertyValue('size') };
  } } catch (e) {} }

  const declared = new Set();
  const GENERIC = /^(serif|sans-serif|monospace|system-ui|ui-monospace|cursive|fantasy|-apple-system|inherit)$/i;
  const addFamilies = ff => ff.split(',').forEach(f => {
    f = f.trim().replace(/^["']|["']$/g, '');
    if (f && !GENERIC.test(f)) declared.add(f); });
  const walkFonts = rules => { for (const r of rules) {
    if (r.style) { const ff = r.style.getPropertyValue('font-family'); if (ff) addFamilies(ff); }
    else if (r.cssRules) walkFonts(r.cssRules); } };
  for (const s of document.styleSheets) { try { walkFonts(s.cssRules); } catch (e) {} }
  const resolved = [], missing = [];
  for (const f of declared) (document.fonts.check(`12px "${f}"`) ? resolved : missing).push(f);

  const counts = {};
  const figures = [];
  const figEls = [];
  for (const el of document.querySelectorAll('svg, img, canvas')) {
    if (el.closest('svg') !== el && el.tagName.toLowerCase() === 'svg') continue; // nested svg
    if (el.tagName.toLowerCase() !== 'svg' && el.closest('svg')) continue;
    const r = rectOf(el); if (r.w === 0 && r.h === 0) continue;
    let vb = null;
    if (el.viewBox && el.viewBox.baseVal && el.viewBox.baseVal.width) vb = {w: el.viewBox.baseVal.width, h: el.viewBox.baseVal.height};
    const scale = vb ? Math.min(r.w / vb.w, r.h / vb.h) : 1;
    const hDecl = rulesFor(el, 'height'), wDecl = rulesFor(el, 'width');
    const texts = {};
    for (const t of el.querySelectorAll('text, tspan')) {
      if (t.tagName.toLowerCase() === 'tspan' && t.parentElement.tagName.toLowerCase() === 'text') continue;
      const c = t.getAttribute('class') || '';
      const fs = px(cs(t).fontSize);
      const k = c || '';
      if (!(k in texts) || texts[k].computed_px < fs) texts[k] = {class: c, computed_px: fs, realised_px: fs * scale};
    }
    figEls.push(el);
    figures.push({selector: sel(el, 0, counts), tag: el.tagName.toLowerCase(),
      classes: [...el.classList], data_fig_role: el.dataset.figRole || null,
      rect: r, viewbox: vb, scale, parent_w: (el.parentElement ? el.parentElement.getBoundingClientRect().width : r.w),
      css_height_is_auto: !hDecl || hDecl === 'auto',
      css_width_is_pct: !!wDecl && wDecl.trim().endsWith('%'),
      preserve_aspect_ratio: el.getAttribute('preserveAspectRatio') || null,
      texts: Object.values(texts)});
  }
  const qcounts = {};
  const qa = [...document.querySelectorAll('.qa, [data-qid]')].map(el => {
    const r = rectOf(el); return {selector: sel(el, 0, qcounts), qid: el.dataset.qid || null,
      classes: [...el.classList], offset_top: r.y, offset_height: r.h, rect: r}; });
  const hcounts = {};
  const headings = [...document.querySelectorAll('h1,h2,h3,h4')].map(el => ({
    level: +el.tagName[1], text: el.textContent.trim().replace(/\s+/g, ' ').slice(0, 120),
    selector: sel(el, 0, hcounts), offset_top: rectOf(el).y, rect: rectOf(el),
    break_before: cs(el).breakBefore }));

  // blocks: elements that directly own visible text, plus figures, tables,
  // and empty sized boxes (answer space). Used by the spacing checks.
  const bcounts = {};
  const blocks = [];
  const BLOCKTAGS = new Set(['P','DIV','H1','H2','H3','H4','LI','TD','TH','TABLE','SVG','IMG','SECTION','FIGURE','SPAN','B','I','LABEL','OL','UL']);
  const lines = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (el.closest('svg') && el.tagName.toLowerCase() !== 'svg') continue;
    const tag = el.tagName.toUpperCase();
    const st = cs(el);
    if (st.display === 'none' || st.visibility === 'hidden') continue;
    const r = rectOf(el); if (r.w < 2 || r.h < 2) continue;
    let kind = null;
    if (tag === 'SVG' || tag === 'IMG' || tag === 'CANVAS') kind = 'figure';
    else if (tag === 'TABLE') kind = 'table';
    else {
      const ownText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
      if (ownText && BLOCKTAGS.has(tag) && st.display !== 'inline') kind = 'text';
      else if (ownText && st.display === 'inline') continue;
      else if (!el.textContent.trim() && !el.querySelector('svg,img,table') && r.h >= 24 &&
               (rulesFor(el, 'height') || rulesFor(el, 'min-height') || tag === 'TD')) kind = 'space';
    }
    if (!kind) continue;
    const b = {selector: sel(el, 0, bcounts), tag: tag.toLowerCase(), classes: [...el.classList],
      rect: r, kind, font_px: px(st.fontSize), line_height_px: px(st.lineHeight) || px(st.fontSize) * 1.2,
      data_role: el.dataset.role || null, data_for: el.dataset.for || null,
      qa: (el.closest('.qa, [data-qid]') || {}).dataset ? (el.closest('.qa, [data-qid]').dataset.qid || sel_of_qa(el)) : null};
    blocks.push(b);
    if (kind === 'text' && lines.length < 4000) {
      for (const n of el.childNodes) { if (n.nodeType !== 3 || !n.textContent.trim()) continue;
        const rg = document.createRange(); rg.selectNodeContents(n);
        for (const lr of rg.getClientRects()) if (lr.height > 0)
          lines.push({y_top: lr.top + sy, y_bottom: lr.bottom + sy, x_left: lr.left + sx, x_right: lr.right + sx, block: b.selector}); }
    }
  }
  // atoms: the unbreakable units of vertical flow, in document order. An
  // element is an atom when it must be kept together (break-inside:avoid, or a
  // flex/grid/table container) or when it has no block-level children;
  // otherwise its children are visited.
  const acounts = {};
  const atoms = [];
  const atomEls = [];
  const ihEls = [...document.body.querySelectorAll('[style]')]
    .filter(el => el.style.height && !el.closest('svg') && cs(el).display !== 'none');
  const isRow = k => { const ks = cs(k); return /^(flex|grid|inline-flex|inline-grid)$/.test(ks.display) && ks.flexDirection !== 'column' &&
    [...k.children].filter(c => cs(c).display !== 'none' && c.getBoundingClientRect().width > 0).length >= 2 &&
    [...k.children].filter(c => cs(c).display !== 'none' && c.getBoundingClientRect().height > 0).every(c => Math.abs(c.getBoundingClientRect().top - k.getBoundingClientRect().top) < 4); };
  const isBlockish = st => /^(block|flex|grid|table|list-item|flow-root)/.test(st.display);
  const visit = (el, group) => {
    const st = cs(el);
    if (st.display === 'none') return;
    const r = rectOf(el); if (r.h < 1) return;
    const kids = [...el.children].filter(k => { const ks = cs(k); if (ks.display === 'none' || k.getBoundingClientRect().height <= 0) return false;
      const t = k.tagName.toLowerCase();
      return isBlockish(ks) || t === 'svg' || t === 'img' || !!k.querySelector('svg,img,table') || !!k.style.height; });
    const avoid = st.breakInside === 'avoid' || st.breakInside === 'avoid-page' || st.pageBreakInside === 'avoid';
    const container = /^(flex|grid|table|inline-flex|inline-grid)$/.test(st.display);
    const tag = el.tagName.toLowerCase();
    const tooTall = r.h > 0.9 * __CONTENT_H__ && tag !== 'svg' && tag !== 'table' && kids.length > 1;
    const ownText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!tooTall && (avoid || container || kids.length === 0 || ownText || tag === 'table' || tag === 'svg')) {
      const figs = tag === 'svg' ? [el] : [...el.querySelectorAll('svg, img')];
      const figSel = figs.map(f => figures.find(g => g.rect.x === (f.getBoundingClientRect().left + sx) && g.rect.y === (f.getBoundingClientRect().top + sy))).filter(Boolean).map(g => g.selector);
      const spaces = [el, ...el.querySelectorAll('*')].filter(k => !k.closest('svg') && !k.textContent.trim() && !k.querySelector('svg,img,table') && k.getBoundingClientRect().height >= 24 && (k.style.height || rulesFor(k, 'height')));
      const h = el.matches('h1,h2,h3,h4') ? el : el.querySelector('h1,h2,h3,h4');
      // the height this atom keeps if every figure in it shrank to nothing:
      // a figure beside a text column only frees height down to that column
      let figFloor = r.h;
      for (const f of figs) {
        let col = f, par = f.parentElement;
        while (par && par !== el && !/^(flex|grid|inline-flex|inline-grid|table)/.test(cs(par).display)) { col = par; par = par.parentElement; }
        const rowLike = par && /^(flex|grid|inline-flex|inline-grid|table)/.test(cs(par).display) && cs(par).flexDirection !== 'column';
        if (!rowLike) { figFloor -= f.getBoundingClientRect().height; continue; }
        const sibs = [...par.children].filter(k => k !== col && !k.querySelector('svg,img') && k.tagName.toLowerCase() !== 'svg');
        const T = Math.max(0, ...sibs.map(k => k.getBoundingClientRect().height));
        figFloor -= Math.max(0, col.getBoundingClientRect().height - T);
      }
      // side-by-side rows inside the atom: height = max over columns
      const rowEls = (isRow(el) ? [el] : [...el.querySelectorAll('*')].filter(isRow))
        .filter(rw => rw === el || ![...el.querySelectorAll('*')].some(o => o !== rw && o.contains(rw) && isRow(o)));
      const rows = rowEls.map(rw => ({h: rw.getBoundingClientRect().height,
        cols: [...rw.children].filter(c => cs(c).display !== 'none').map(c => ({
          h: c.getBoundingClientRect().height,
          figs: figEls.map((fe, n) => (c === fe || c.contains(fe)) ? n : -1).filter(n => n >= 0),
          boxes: ihEls.map((ie, n) => (c === ie || c.contains(ie)) ? n : -1).filter(n => n >= 0)}))}));
      atomEls.push(el);
      atoms.push({selector: sel(el, 0, acounts), tag: el.tagName.toLowerCase(), classes: [...el.classList], rows,
        rect: r, avoid, fig_floor: Math.max(0, figFloor),
        text: el.textContent.trim().replace(/\s+/g, ' ').slice(0, 80),
        heading: h ? h.textContent.trim().replace(/\s+/g, ' ').slice(0, 120) : null,
        heading_level: h ? +h.tagName[1] : null,
        break_before: st.breakBefore === 'page' || st.breakBefore === 'always' || st.pageBreakBefore === 'always' || (h && (cs(h).breakBefore === 'page' || cs(h).breakBefore === 'always')),
        figures: figSel,
        spaces: spaces.map(k => ({classes: [...k.classList], rect: rectOf(k), inline_height: k.style.height || null})),
        qa: el.matches('.qa,[data-qid]') || !!el.querySelector('.qa,[data-qid]'),
        group: group || null});
      return;
    }
    // a keep-together block taller than a page: its children become atoms
    // that must share a page and fit on it together
    const g = (tooTall && avoid) ? ('group:' + sel(el, 0, acounts)) : group;
    for (const k of kids) visit(k, g);
  };
  for (const k of document.body.children) visit(k, null);
  // every element with an inline height, in document order: the answer-space
  // knobs the fitter may edit in the source by occurrence index
  const inline_heights = ihEls.map(el => ({classes: [...el.classList], rect: rectOf(el), height: el.style.height,
                 empty: !el.textContent.trim(), atom: atomEls.findIndex(a => a === el || a.contains(el))}));
  function sel_of_qa(el) { const q = el.closest('.qa, [data-qid]'); if (!q) return null;
    const i = [...document.querySelectorAll('.qa, [data-qid]')].indexOf(q); return i >= 0 ? qa[i].selector : null; }
  return {body_font_px: px(cs(document.body).fontSize), doc_client_w: document.documentElement.clientWidth,
    doc_scroll_h: document.documentElement.scrollHeight,
    body_rect: rectOf(document.body), page_rule: pageRule,
    fonts: {declared: [...declared], resolved, missing},
    figures, qa, headings, blocks, lines, atoms, inline_heights,
    media_print: matchMedia('print').matches};
})()
"""


def find_chrome() -> str:
    env = os.environ.get("PRINTFIT_CHROME")
    if env and not (os.path.isfile(env) and os.access(env, os.X_OK)):
        raise HarnessError(
            f"PRINTFIT_CHROME is set to {env!r}, which is not an executable file. "
            "Fix the path or unset PRINTFIT_CHROME to search the default locations.")
    cands = [env] if env else []
    cands += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    raise HarnessError(
        "Google Chrome or Chromium not found. Install one of them, or set "
        "PRINTFIT_CHROME to the browser executable.")


_LEN = re.compile(r"([-\d.]+)\s*(in|px|pt|mm|cm)")


def _len_px(v: str | None) -> float | None:
    if not v:
        return None
    m = _LEN.match(v.strip())
    if not m:
        return None
    n, u = float(m.group(1)), m.group(2)
    return n * {"in": 96, "px": 1, "pt": PT, "mm": 96 / 25.4, "cm": 96 / 2.54}[u]


def _page_margins(page_rule: dict | None) -> tuple[dict[str, float], str]:
    d = CHROME_DEFAULT_MARGIN_PX
    m = {"top": d, "right": d, "bottom": d, "left": d}
    if not page_rule:
        return m, "chrome_default"
    any_set = False
    for k in m:
        v = _len_px(page_rule.get("margin" + k.capitalize())) or _len_px(page_rule.get("margin"))
        if v is not None:
            m[k] = v
            any_set = True
    return m, ("css_page_rule" if any_set else "chrome_default")


def _paper_size(page_rule: dict | None) -> tuple[float, float]:
    size = (page_rule or {}).get("size", "") or ""
    s = size.lower()
    if "a4" in s:
        return (A4_H_PX, A4_W_PX) if "landscape" in s else (A4_W_PX, A4_H_PX)
    m = re.findall(r"([-\d.]+)\s*(in|px|pt|mm|cm)", s)
    if len(m) == 2:
        return _len_px(f"{m[0][0]}{m[0][1]}"), _len_px(f"{m[1][0]}{m[1][1]}")
    return (LETTER_H_PX, LETTER_W_PX) if "landscape" in s else (LETTER_W_PX, LETTER_H_PX)


class _CDP:
    def __init__(self, chrome: str, width: int = 800, height: int = 1000):
        self.tmp = tempfile.mkdtemp(prefix="printfit-chrome-")
        self.proc = subprocess.Popen(
            [chrome, "--headless=new", "--disable-gpu", "--no-first-run",
             "--no-default-browser-check", "--hide-scrollbars",
             "--remote-debugging-port=0", f"--user-data-dir={self.tmp}",
             f"--window-size={width},{height}", "about:blank"]
            # Opt-in for Linux CI runners (Ubuntu 24.04) where Chrome's sandbox cannot start.
            + (["--no-sandbox"] if os.environ.get("PRINTFIT_NO_SANDBOX") else []),
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        self.port = None
        deadline = time.time() + 20
        while time.time() < deadline:
            line = self.proc.stderr.readline()
            m = re.search(r"DevTools listening on ws://127\.0\.0\.1:(\d+)/", line)
            if m:
                self.port = int(m.group(1))
                break
            if self.proc.poll() is not None:
                break
        if not self.port:
            self.close()
            raise HarnessError("Chrome did not expose a DevTools port")
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/json/new?about:blank", method="PUT")
        info = json.loads(urllib.request.urlopen(req, timeout=10).read())
        self.ws = websocket.create_connection(info["webSocketDebuggerUrl"], timeout=60,
                                              suppress_origin=True)
        self._id = 0
        self.version = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/json/version", timeout=10).read()).get("Browser", "")

    def send(self, method: str, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise HarnessError(f"CDP {method}: {msg['error']}")
                return msg.get("result", {})

    def wait_event(self, name: str, timeout: float = 30):
        self.ws.settimeout(timeout)
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("method") == name:
                return msg.get("params", {})

    def evaluate(self, js: str, await_promise: bool = False):
        r = self.send("Runtime.evaluate", expression=js, returnByValue=True,
                      awaitPromise=await_promise)
        res = r.get("result", {})
        if "exceptionDetails" in r:
            raise HarnessError(f"geometry script failed: {r['exceptionDetails'].get('text')} "
                               f"{res.get('description', '')}")
        return res.get("value")

    def close(self):
        try:
            if getattr(self, "ws", None):
                self.ws.close()
        finally:
            self.proc.kill()
            self.proc.wait()
            shutil.rmtree(self.tmp, ignore_errors=True)


def capture_geometry(html_path: str) -> dict:
    """Return per-element geometry with print media emulated. Convenience
    wrapper; `render` does this and more in one browser lifetime."""
    return render(html_path, tempfile.mkdtemp(prefix="printfit-geom-")).dom_geometry


def render(html_path: str, out_dir: str, raster_dpi: int = 150,
           renderer: str = "cdp") -> RenderArtifacts:
    """Render `html_path` once, producing PDF, per-page PNGs, and geometry."""
    if renderer != "cdp":
        raise HarnessError("only the cdp renderer is implemented")
    html_path = os.path.abspath(html_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome()
    cdp = _CDP(chrome)
    try:
        cdp.send("Page.enable")
        cdp.send("Emulation.setEmulatedMedia", media="print")
        cdp.send("Page.navigate", url="file://" + html_path)
        cdp.wait_event("Page.loadEventFired")
        # first pass: read @page so the layout viewport can match the paper
        page_rule = cdp.evaluate(
            "(()=>{let p=null;for(const s of document.styleSheets){try{for(const r of s.cssRules)"
            "if(r.type===CSSRule.PAGE_RULE)p={marginTop:r.style.marginTop,marginRight:r.style.marginRight,"
            "marginBottom:r.style.marginBottom,marginLeft:r.style.marginLeft,margin:r.style.margin,"
            "size:r.style.getPropertyValue('size')}}catch(e){}}return p})()")
        margins, margin_source = _page_margins(page_rule)
        paper_w, paper_h = _paper_size(page_rule)
        content_w = paper_w - margins["left"] - margins["right"]
        content_h = paper_h - margins["top"] - margins["bottom"]
        cdp.send("Emulation.setDeviceMetricsOverride", width=int(round(content_w)),
                 height=int(round(content_h)), deviceScaleFactor=1, mobile=False)
        cdp.evaluate("document.fonts.ready.then(()=>true)", await_promise=True)
        geom = cdp.evaluate(GEOMETRY_JS.replace("__CONTENT_H__", f"{content_h:.1f}"))
        if geom is None:
            raise HarnessError("geometry script returned nothing")
        if abs(geom["doc_client_w"] - content_w) > 2:
            raise HarnessError(f"@page cross-check failed: content width {content_w:.1f}px "
                               f"but document clientWidth {geom['doc_client_w']}px")
        pdf = cdp.send("Page.printToPDF", printBackground=True, preferCSSPageSize=True,
                       displayHeaderFooter=False,
                       paperWidth=paper_w / 96, paperHeight=paper_h / 96,
                       marginTop=margins["top"] / 96, marginBottom=margins["bottom"] / 96,
                       marginLeft=margins["left"] / 96, marginRight=margins["right"] / 96)
        version = cdp.version
    finally:
        cdp.close()
    pdf_path = str(out / "render.pdf")
    with open(pdf_path, "wb") as fh:
        fh.write(base64.b64decode(pdf["data"]))

    pdf_geom = page_geometry_from_pdf(pdf_path)
    if abs(pdf_geom["paper_w_px"] - paper_w) > 2 or abs(pdf_geom["paper_h_px"] - paper_h) > 2:
        raise HarnessError(f"PDF paper {pdf_geom['paper_w_px']:.0f}x{pdf_geom['paper_h_px']:.0f}px "
                           f"disagrees with @page {paper_w:.0f}x{paper_h:.0f}px")
    pngs = rasterise(pdf_path, str(out), raster_dpi)
    heads = geom.get("headings", [])
    pmap = page_map(pdf_geom, heads)
    geom["page_map"] = pmap
    geom["pdf"] = pdf_geom
    explicit_breaks = _explicit_break_pages(heads, pmap)
    pages = []
    n = pdf_geom["page_count"]
    for p in pdf_geom["pages"]:
        ink_bottom = p["ink_bottom_px"] - margins["top"]
        slack = content_h - ink_bottom
        pages.append(PageMetrics(index=p["index"], fill_ratio=max(0.0, min(ink_bottom / content_h, 1.0)),
                                 slack_px=slack, ends_in_explicit_break=p["index"] in explicit_breaks,
                                 is_final=p["index"] == n))
    art = RenderArtifacts(
        pdf_path=pdf_path, page_png_paths=pngs, dom_geometry=geom, page_count=n,
        page_content_h_px=content_h, page_content_w_px=content_w,
        body_font_px=float(geom["body_font_px"]), pages=pages,
        fonts_resolved=geom["fonts"]["resolved"], fonts_missing=geom["fonts"]["missing"],
        chrome_version=version, paper_w_px=paper_w, paper_h_px=paper_h,
        raster_dpi=raster_dpi, chrome_path=chrome, media_emulation="cdp",
        page_margin_source=margin_source)
    save_artifacts(art, str(out / "geometry.json"))
    return art


def _explicit_break_pages(headings: list[dict], pmap: dict[str, int]) -> set[int]:
    """Pages whose NEXT page starts with a heading carrying break-before:page."""
    out = set()
    for h in headings:
        if h.get("break_before") in ("page", "always", "left", "right"):
            p = pmap.get(h["text"])
            if p and p > 1:
                out.add(p - 1)
    return out


def rasterise(pdf_path: str, out_dir: str, dpi: int) -> list[str]:
    doc = pymupdf.open(pdf_path)
    paths = []
    for i, page in enumerate(doc, 1):
        p = os.path.join(out_dir, f"page-{i}.png")
        page.get_pixmap(dpi=dpi).save(p)
        paths.append(p)
    doc.close()
    return paths


def page_geometry_from_pdf(pdf_path: str) -> dict:
    """{'page_count', 'paper_w_px', 'paper_h_px', 'pages':[{'index',
    'ink_bottom_px','ink_top_px','ink_area_px2'}], 'page_text':[...]}
    pdfplumber; every point value converted pt*96/72 before it leaves here.
    Page count from the PDF object tree, never from extracted text."""
    doc = pymupdf.open(pdf_path)
    count = len(doc)
    w, h = doc[0].rect.width * PT, doc[0].rect.height * PT
    doc.close()
    pages, texts = [], []
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            bottom, top, area = 0.0, page.height, 0.0
            page_area = page.width * page.height
            for coll in (page.chars, page.rects, page.lines, page.curves, page.images):
                for o in coll:
                    if _is_background(o, page_area):
                        continue
                    bottom = max(bottom, o["bottom"])
                    top = min(top, o["top"])
                    area += o["width"] * o["height"]
            texts.append(page.extract_text() or "")
            pages.append({"index": i, "ink_bottom_px": bottom * PT, "ink_top_px": top * PT,
                          "ink_area_px2": area * PT * PT})
    return {"page_count": count, "paper_w_px": w, "paper_h_px": h, "pages": pages,
            "page_text": texts}


def _is_background(o: dict, page_area: float) -> bool:
    """A filled, unstroked shape that is (near-)white, or that covers most of
    the page, is a background box, not ink. Rules and borders are 1px and
    stroked, and survive."""
    if o.get("object_type") not in ("rect", "curve"):
        return False
    if o.get("stroke"):
        return False
    col = o.get("non_stroking_color")
    comps = col if isinstance(col, (tuple, list)) else ((col,) if isinstance(col, (int, float)) else ())
    if comps and all(c >= 0.94 for c in comps):
        return True
    return o["width"] * o["height"] > 0.5 * page_area


def page_map(pdf_geom: dict, headings: list[dict]) -> dict[str, int]:
    """Section heading -> 1-based page, by matching heading text against
    per-page extracted text. Ground truth, and text-only by construction."""
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()
    pages = [norm(t) for t in pdf_geom["page_text"]]
    out: dict[str, int] = {}
    last = 0
    for h in headings:
        key = norm(h["text"])
        if not key:
            continue
        probe = key[:40]
        for i in range(last, len(pages)):
            if probe in pages[i]:
                out[h["text"]] = i + 1
                last = i
                break
    return out


def save_artifacts(art: RenderArtifacts, path: str) -> None:
    d = dataclasses.asdict(art)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=1)


def load_artifacts(path: str) -> RenderArtifacts:
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    d["pages"] = [PageMetrics(**p) for p in d["pages"]]
    return RenderArtifacts(**d)
