"""Tiny source-only CSS reader shared by the preflights and the fitter.
Not a CSS parser: it reads `selector{decls}` blocks from <style> text, which
is the whole of what generated worksheets use."""
from __future__ import annotations

import re

_STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
_BLOCK = re.compile(r"([^{}]+)\{([^{}]*)\}")
_LEN = re.compile(r"^\s*([-\d.]+)\s*(in|px|pt|mm|cm|%)\s*$")

PX_PER = {"in": 96.0, "px": 1.0, "pt": 96 / 72, "mm": 96 / 25.4, "cm": 96 / 2.54}


def style_text(src: str) -> str:
    return "\n".join(m.group(1) for m in _STYLE.finditer(src))


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
