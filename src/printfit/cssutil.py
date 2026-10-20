"""Source-only CSS reading shared by the preflights and the fitter.

`rules` is the tiny reader: `selector{decls}` blocks from <style> text, which
is the whole of what generated worksheets use. `Cascade` resolves those rules
against the parsed document the way print media would -- real selector
matching, specificity, source order, inline style, inheritance for font size
-- so a preflight can say what Chrome will compute without launching it."""
from __future__ import annotations

import re

import cssselect
import cssselect.xpath
import lxml.etree
import lxml.html

_STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)
_BLOCK = re.compile(r"([^{}]+)\{([^{}]*)\}")
_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LEN = re.compile(r"^\s*([-\d.]+)\s*(in|px|pt|mm|cm|%)\s*$")

PX_PER = {"in": 96.0, "px": 1.0, "pt": 96 / 72, "mm": 96 / 25.4, "cm": 96 / 2.54}


def style_text(src: str) -> str:
    css = "\n".join(m.group(1) for m in _STYLE.finditer(src))
    return _COMMENT.sub("", css)    # a comment left in place glues itself to the next selector


def rules(src: str) -> list[tuple[str, dict[str, str], bool]]:
    """[(selector, {prop: value}, in_print_block)] in source order.
    @media blocks are flattened; the flag records whether the rule sat inside
    `@media print`."""
    css = style_text(src)
    out = []
    # split top-level @media blocks
    pos = 0
    for m in re.finditer(r"@media([^{]*)\{", css):
        start = m.end()
        depth = 1
        i = start
        while i < len(css) and depth:
            depth += css[i] == "{"
            depth -= css[i] == "}"
            i += 1
        out += _blocks(css[pos:m.start()], False)
        out += _blocks(css[start:i - 1], "print" in m.group(1))
        pos = i
    out += _blocks(css[pos:], False)
    return out


def _blocks(css: str, in_print: bool):
    res = []
    for sel, body in _BLOCK.findall(css):
        sel = sel.strip()
        if sel.startswith("@"):
            continue
        decls = {}
        for d in body.split(";"):
            if ":" in d:
                k, v = d.split(":", 1)
                decls[k.strip().lower()] = v.strip()
        for s in sel.split(","):
            res.append((s.strip(), decls, in_print))
    return res


def to_px(value: str | None) -> float | None:
    """Absolute length -> CSS px; None for auto/percent/missing."""
    if not value:
        return None
    m = _LEN.match(value.replace("!important", ""))
    if not m or m.group(2) == "%":
        return None
    return float(m.group(1)) * PX_PER[m.group(2)]


def declared(rules_list, classes: list[str], tag: str, prop: str,
             prefer_print: bool = True) -> str | None:
    """Last matching declaration of `prop` for an element with `tag` and
    `classes`, over simple selectors `tag`, `.c`, `tag.c`, `tag.c1.c2`."""
    val = None
    for sel, decls, in_print in rules_list:
        if prop not in decls:
            continue
        if _matches(sel, tag, classes):
            if in_print and not prefer_print:
                continue
            val = decls[prop]
    return val


def _matches(sel: str, tag: str, classes: list[str]) -> bool:
    sel = sel.split()[-1] if sel.strip() else sel     # descendant: last part
    if any(c in sel for c in ":>+~[#"):
        return False
    parts = sel.split(".")
    stag, scls = parts[0], parts[1:]
    if stag and stag != "*" and stag != tag:
        return False
    return all(c in classes for c in scls)


def body_width_px(src: str, print_media: bool = True) -> float:
    """Declared body max-width/width in the print block if present, else the
    screen value, else 7.5in (US Letter minus 0.5in margins)."""
    rl = rules(src)
    best = None
    for sel, decls, in_print in rl:
        if sel == "body":
            for prop in ("max-width", "width"):
                px = to_px(decls.get(prop))
                if px and (in_print or best is None or not print_media):
                    best = px
    return best or 7.5 * 96


# --- static cascade -----------------------------------------------------------

_UA_FONT = {"xx-small": 9.0, "x-small": 10.0, "small": 13.0, "medium": 16.0,
            "large": 18.0, "x-large": 24.0, "xx-large": 32.0}
_FONT_SIZE_IN_SHORTHAND = re.compile(
    r"(?:^|\s)((?:\d*\.)?\d+(?:px|pt|em|rem|%|in|mm|cm)|" + "|".join(_UA_FONT) + r")(?:\s*/\s*\S+)?\s")
_PCT = re.compile(r"^\s*([-\d.]+)\s*%\s*$")


def media_rules(src: str) -> list[tuple[str, dict[str, str], str]]:
    """[(selector, decls, media)] in source order, media one of all | print |
    screen. Unlike `rules`, `@media screen` blocks are kept apart so print
    resolution can drop them."""
    css = style_text(src)
    out, pos = [], 0
    for m in re.finditer(r"@media([^{]*)\{", css):
        start, depth, i = m.end(), 1, m.end()
        while i < len(css) and depth:
            depth += css[i] == "{"
            depth -= css[i] == "}"
            i += 1
        q = m.group(1).lower()
        media = "print" if "print" in q else ("screen" if "screen" in q else "all")
        out += [(s, d, "all") for s, d, _ in _blocks(css[pos:m.start()], False)]
        out += [(s, d, media) for s, d, _ in _blocks(css[start:i - 1], False)]
        pos = i
    out += [(s, d, "all") for s, d, _ in _blocks(css[pos:], False)]
    return out


def _decls(text: str) -> dict[str, str]:
    out = {}
    for d in (text or "").split(";"):
        if ":" in d:
            k, v = d.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


class Cascade:
    """Cascaded values for the elements of one document under print media.

    Not a layout engine: widths resolve through absolute lengths, percentages,
    flex bases and equal grid tracks, and anything past that is reported as
    an estimate (`exact=False`) rather than guessed silently."""

    def __init__(self, src: str):
        self.src = src
        self.tree = lxml.html.document_fromstring(src)
        self._rules: dict = {}
        tr = cssselect.GenericTranslator()
        for order, (sel, decls, media) in enumerate(media_rules(src)):
            if media == "screen" or "::" in sel or not sel:
                continue
            try:
                spec = cssselect.parse(sel)[0].specificity()
                xp = tr.css_to_xpath(sel)
                hits = self.tree.xpath(xp)
            except (cssselect.SelectorError, cssselect.xpath.ExpressionError, lxml.etree.XPathError):
                continue            # :hover and other pseudos with no static meaning
            for el in hits:
                self._rules.setdefault(el, []).append((spec, order, decls))
        self._font: dict = {}
        self.page_w, self.page_h = self._page_box()

    def body(self):
        b = self.tree.find(".//body")
        return b if b is not None else self.tree

    def value(self, el, *props: str) -> tuple[str | None, str | None]:
        """(prop, value) of the winning declaration among `props` for `el`:
        !important, then inline style, then specificity, then source order.
        Presentation attributes (`width=`, `font-size=`) rank below all CSS."""
        best, key = (None, None), None
        for spec, order, decls in self._rules.get(el, []):
            for p in props:
                if p in decls:
                    v = decls[p]
                    k = ("!important" in v, 0, spec, order)
                    if key is None or k >= key:
                        best, key = (p, v.replace("!important", "").strip()), k
        inline = _decls(el.get("style"))
        for p in props:
            if p in inline:
                v = inline[p]
                k = ("!important" in v, 1, (0, 0, 0), 1 << 30)
                if key is None or k >= key:
                    best, key = (p, v.replace("!important", "").strip()), k
        if best[0] is None:
            for p in props:
                if el.get(p) is not None:
                    return p, el.get(p)
        return best

    # -- font size -------------------------------------------------------------
    def font_px(self, el) -> float:
        """Computed font-size in CSS px (SVG user units inside an svg)."""
        if el in self._font:
            return self._font[el]
        par = el.getparent()
        parent = self.font_px(par) if par is not None else 16.0
        prop, v = self.value(el, "font-size", "font")
        size = parent
        if v:
            if prop == "font":
                m = _FONT_SIZE_IN_SHORTHAND.search(" " + v + " ")
                v = m.group(1) if m else None
            if v:
                size = self._font_len(v.strip(), parent)
        self._font[el] = size
        return size

    def _font_len(self, v: str, parent: float) -> float:
        if v in _UA_FONT:
            return _UA_FONT[v]
        if v == "smaller":
            return parent / 1.2
        if v == "larger":
            return parent * 1.2
        m = re.match(r"^([-\d.]+)\s*(px|pt|in|mm|cm|em|rem|%)?$", v)
        if not m:
            return parent
        n, u = float(m.group(1)), m.group(2)
        if u in (None, "px"):
            return n
        if u == "em":
            return n * parent
        if u == "%":
            return n * parent / 100
        if u == "rem":
            return n * self.font_px(self.tree)
        return n * PX_PER[u]

    # -- widths ------------------------------------------------------------------
    def _page_box(self) -> tuple[float, float]:
        """Printable content box (px) from @page; Chrome's 1cm default margins."""
        from .render import _page_margins, _paper_size
        m = re.search(r"@page[^{]*\{([^}]*)\}", style_text(self.src))
        rule = None
        if m:
            d = _decls(m.group(1))
            rule = {"margin": d.get("margin", ""), "size": d.get("size", "")}
            for side in ("Top", "Right", "Bottom", "Left"):
                rule["margin" + side] = d.get("margin-" + side.lower(), "")
        margins, _ = _page_margins(rule)
        pw, ph = _paper_size(rule)
        return pw - margins["left"] - margins["right"], ph - margins["top"] - margins["bottom"]

    def _sides(self, el, prop: str, base: float) -> float:
        """Left + right of padding / margin / border-width, in px."""
        total = 0.0
        _, short = self.value(el, prop) if prop != "border" else self.value(el, "border")
        parts = (short or "").split()
        if prop == "border":
            w = next((to_px(t) for t in parts if to_px(t) is not None), 0.0) if parts else 0.0
            return 2 * (w or 0.0)
        lr = ([parts[1 % len(parts)], parts[3] if len(parts) == 4 else parts[1 % len(parts)]]
              if parts else ["0", "0"])
        for side, t in zip(("left", "right"), lr):
            _, v = self.value(el, f"{prop}-{side}")
            t = v or t
            total += to_px(t) or (base * float(_PCT.match(t).group(1)) / 100 if _PCT.match(t) else 0.0)
        if prop == "margin" and el.tag == "body" and short is None and \
                self.value(el, "margin-left")[1] is None:
            total = 16.0                                   # UA body margin 8px
        return total

    def inner_width(self, el) -> tuple[float, bool]:
        """Content-box width (px) children of `el` lay out in, and whether it
        is exact."""
        if el.tag == "html" or el.getparent() is None:
            return self.page_w, True
        pw, exact = self.inner_width(el.getparent())
        par = el.getparent()
        _, pdisp = self.value(par, "display")
        _, disp = self.value(el, "display")
        _, w = self.value(el, "width")
        _, bs = self.value(el, "box-sizing")
        border_box = (bs or "").strip() == "border-box"
        own = None
        if w and to_px(w) is not None:
            own = to_px(w)
        elif w and _PCT.match(w):
            own = pw * float(_PCT.match(w).group(1)) / 100
        elif (pdisp or "").strip() in ("flex", "inline-flex"):
            prop, f = self.value(el, "flex-basis", "flex")
            basis = (f or "").split()[-1] if f else None
            if prop == "flex" and f and len(f.split()) < 3:
                basis = None
            if basis and _PCT.match(basis):
                own = pw * float(_PCT.match(basis).group(1)) / 100
            elif basis and to_px(basis) is not None:
                own = to_px(basis)
            else:
                kids = [k for k in par if isinstance(k.tag, str)]
                own, exact = pw / max(1, len(kids)), False      # flex:1 share, a guess
        elif (pdisp or "").strip() in ("grid", "inline-grid"):
            _, cols = self.value(par, "grid-template-columns")
            n = _equal_tracks(cols)
            _, gap = self.value(par, "column-gap", "gap")
            g = to_px((gap or "0").split()[-1]) or 0.0
            if n:
                own = (pw - g * (n - 1)) / n
            else:
                own, exact = pw, False
        elif (disp or "").strip() in ("inline-block", "table-cell", "inline") or el.tag in ("td", "th"):
            own, exact = pw, False
        _, mw = self.value(el, "max-width")
        mwpx = to_px(mw) if mw else None
        if own is None:
            own = pw - self._sides(el, "margin", pw)
            border_box = True                 # a block's auto width already includes its padding
            if mwpx is not None and mwpx < own:
                own, border_box = mwpx, (bs or "").strip() == "border-box"
        elif mwpx is not None:
            own = min(own, mwpx)
        if border_box:
            own -= self._sides(el, "padding", pw) + self._sides(el, "border", pw)
        return max(own, 0.0), exact


def _equal_tracks(cols: str | None) -> int | None:
    """Track count when every column is the same size (1fr 1fr, repeat(3,1fr))."""
    if not cols:
        return None
    m = re.match(r"^\s*repeat\(\s*(\d+)\s*,\s*([^)]+)\)\s*$", cols)
    if m:
        return int(m.group(1))
    parts = cols.split()
    return len(parts) if parts and len(set(parts)) == 1 else None
