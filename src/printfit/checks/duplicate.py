"""duplicate_content -- edit-induced duplication, measured from the current
document alone.

The structural fingerprint compares two runs, which in check mode fires on
every intended edit. Duplication has a signature visible in one document:
a sizable block whose text appears twice, the same figure twice in a row,
or question numbers that repeat or skip. Loss has no such signature; the
soft structural_delta finding still reports it.
"""
from __future__ import annotations

import hashlib
import re

from lxml import etree
from lxml import html as lxml_html

from ..types import HARD_GATES, Finding
from .structural import _BLOCK_TAGS, _seg

NAME = "duplicate_content"
MIN_DUP_CHARS = 40
QNUM_CLASSES = {"qnum", "q-num", "num"}
_QNUM = re.compile(r"^\s*(\d+)\s*[.)]?\s*$")


def _severity() -> str:
    return "hard" if NAME in HARD_GATES else "soft"


def _text(el) -> str:
    return " ".join(el.text_content().split())


def _section(el) -> str:
    prev = el.xpath("preceding::h2[1]")
    return _text(prev[0]) if prev else "(before the first section)"


def run_html(html_path: str) -> list[Finding]:
    with open(html_path, encoding="utf-8") as fh:
        doc = lxml_html.fromstring(fh.read())
    for bad in doc.xpath("//style|//script"):
        bad.drop_tree()
    return _repeated_blocks(doc) + _adjacent_figures(doc) + _numbering(doc)


def _repeated_blocks(doc) -> list[Finding]:
    out: list[Finding] = []
    first: dict[str, object] = {}
    reported: list = []
    for el in doc.iter():
        if not isinstance(el.tag, str) or el.tag not in _BLOCK_TAGS:
            continue
        if not (el.get("class") or "").strip():
            continue
        if any(r in el.iterancestors() for r in reported):
            continue
        t = _text(el)
        if len(t) < MIN_DUP_CHARS:
            continue
        key = hashlib.sha1(t.encode("utf-8")).hexdigest()
        prior = first.get(key)
        if prior is None:
            first[key] = el
            continue
        if prior in el.iterancestors() or el in prior.iterancestors():
            continue  # a wrapper and its only child share text; not a repeat
        reported.append(el)
        out.append(Finding(
            id=f"{NAME}:block:{_seg(el)}", severity=_severity(),
            message=f"block {_seg(el)} in '{_section(el)}' repeats the text of an earlier "
                    f"block in '{_section(prior)}': \"{t[:60]}...\"",
            selector=_seg(el),
            suggested_fix="delete the repeated block, or change one copy if both are intended"))
    return out


def _adjacent_figures(doc) -> list[Finding]:
    out: list[Finding] = []
    n = 0
    for svg in doc.iter("svg"):
        if svg.xpath("ancestor::svg"):
            continue
        n += 1
        nxt = svg.getnext()
        if nxt is None or nxt.tag != "svg" or (svg.tail or "").strip():
            continue
        if etree.tostring(svg, with_tail=False) == etree.tostring(nxt, with_tail=False):
            out.append(Finding(
                id=f"{NAME}:figure:{n}", severity=_severity(),
                message=f"figure {n} in '{_section(svg)}' is immediately followed by an identical copy",
                suggested_fix="delete the second copy"))
    return out


def _numbering(doc) -> list[Finding]:
    out: list[Finding] = []
    section, nums = "(before the first section)", []

    def flush():
        for i in range(1, len(nums)):
            a, b = nums[i - 1], nums[i]
            if b == a or b in nums[:i - 1]:
                out.append(Finding(id=f"{NAME}:qnum:{section}:{b}", severity=_severity(),
                                   message=f"question number {b} repeats in '{section}'",
                                   suggested_fix="renumber, or delete the repeated question"))
            elif b > a + 1:
                out.append(Finding(id=f"{NAME}:qnum:{section}:{a + 1}", severity=_severity(),
                                   message=f"question numbering skips from {a} to {b} in '{section}'",
                                   suggested_fix="renumber, or restore the missing question"))

    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue
        if el.tag == "h2":
            flush()
            section, nums = _text(el), []
            continue
        if QNUM_CLASSES & set((el.get("class") or "").split()):
            m = _QNUM.match(el.text_content())
            if m:
                nums.append(int(m.group(1)))
    flush()
    return out
