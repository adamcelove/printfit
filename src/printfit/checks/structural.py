"""Structural invariants -- phase 0, and the highest-value guard in the whole
harness.

Every other check catches a document that *looks* wrong. This one catches a
document that is silently *corrupt*: the source session shipped 8 section
headings where there should have been 6, and 23 figures where there should
have been 14, and the document rendered without error.

Assert before and after every automated edit; abort and restore on mismatch.
"""
from __future__ import annotations

import hashlib
import re

from lxml import html as lxml_html

from ..types import Finding

_VB = re.compile(r"viewBox\s*=\s*[\"']\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)")

# Block-level tags whose per-element fingerprint catches nesting corruption
# that counts alone miss: a div whose opening line moved elsewhere leaves
# every count (h1, h2, svg, qa, text_len) unchanged.
_BLOCK_TAGS = {"div", "section", "p", "ul", "ol", "li", "h1", "h2", "h3",
              "table", "figure", "svg"}


def _parse(html_path: str):
    src = open(html_path, encoding="utf-8").read()
    # Fragments without <html>/<body> parse fine under lxml.html; it
    # synthesises the missing wrappers exactly as Chrome does.
    return lxml_html.fromstring(src), src


def fingerprint(html_path: str) -> dict:
    """Count headings, figures, question groups, and total visible text
    length. Cheap, and sufficient to detect duplication or loss."""
    doc, src = _parse(html_path)
    for bad in doc.xpath("//style|//script"):
        bad.drop_tree()
    text = " ".join(doc.text_content().split())
    svgs = doc.xpath("//svg")
    boxes = []
    for s in svgs:
        vb = s.get("viewbox") or s.get("viewBox")
        if vb:
            parts = vb.split()
            if len(parts) == 4:
                boxes.append([float(parts[2]), float(parts[3])])
    return {
        "h1": len(doc.xpath("//h1")),
        "h2": len(doc.xpath("//h2")),
        "svg": len(svgs),
        "qa": len(doc.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' qa ')]")),
        "text_len": len(text),
        "svg_viewboxes": boxes,
        "blocks": _block_fingerprints(doc),
    }


def _seg(el) -> str:
    cls = (el.get("class") or "").split()
    return f"{el.tag}." + ".".join(cls) if cls else el.tag


def _path(el) -> str:
    segs = []
    cur = el
    while cur is not None:
        segs.append("body" if cur.tag == "body" else _seg(cur))
        if cur.tag == "body":
            break
        cur = cur.getparent()
    return ">".join(reversed(segs))


def _block_fingerprints(doc) -> list[dict]:
    out = []
    for el in doc.iter():
        if el.tag not in _BLOCK_TAGS:
            continue
        cls = (el.get("class") or "").strip()
        if not cls:
            continue
        text = " ".join(el.text_content().split())
        n_children = len(list(el))
        if not text and not n_children:
            continue  # decorative/empty elements (e.g. a spacer div) carry no content signal
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        out.append({"path": _path(el), "text_sha1": digest, "n_children": n_children})
    return out


def compare(before: dict, after: dict) -> list[Finding]:
    """Fail on any divergence. Content is never a thing the fitter may
    change -- only its arrangement."""
    out: list[Finding] = []
    for key in ("h1", "h2", "svg", "qa", "text_len"):
        if before.get(key) != after.get(key):
            out.append(Finding(
                id=f"structural:{key}", severity="hard",
                message=f"{key} changed {before.get(key)} -> {after.get(key)}: "
                        "content was duplicated or lost by an edit",
                value=float(after.get(key) or 0),
                threshold=float(before.get(key) or 0)))
    if sorted(map(tuple, before.get("svg_viewboxes", []))) != \
            sorted(map(tuple, after.get("svg_viewboxes", []))):
        out.append(Finding(id="structural:svg_viewboxes", severity="hard",
                           message="the set of SVG viewBoxes changed"))
    out += _compare_blocks(before.get("blocks", []), after.get("blocks", []))
    return out


def _compare_blocks(before: list[dict], after: list[dict]) -> list[Finding]:
    out: list[Finding] = []
    bkey = [(b["path"], b["text_sha1"]) for b in before]
    akey = [(b["path"], b["text_sha1"]) for b in after]
    if before and after and sorted(bkey) != sorted(akey):
        from collections import Counter
        bc, ac = Counter(bkey), Counter(akey)
        only_before = list((bc - ac).elements())
        only_after = list((ac - bc).elements())
        names = [p for p, _ in (only_before + only_after)][:3]
        out.append(Finding(
            id="structural:blocks", severity="hard",
            message=f"block content/nesting diverged; paths only before or after: {names}"))
        return out
    if before and after and bkey != akey:
        out.append(Finding(
            id="structural:nesting", severity="hard",
            message="the same blocks are present but their document order changed: "
                    "a block was moved"))
    return out
