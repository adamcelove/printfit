"""Print colour preflight. Soft: a background that Chrome drops on paper is a
legibility loss, not a layout one."""
from __future__ import annotations

from .. import cssutil
from ..types import Finding


def preflight_print_color(html_path: str) -> list[Finding]:
    """Any rule setting `background` to a non-white colour whose selector is not
    covered by a `print-color-adjust: exact` (or -webkit-) declaration."""
    src = open(html_path, encoding="utf-8").read()
    rl = cssutil.rules(src)
    exact: set[str] = set()
    for sel, decls, _ in rl:
        if any(k in decls for k in ("print-color-adjust", "-webkit-print-color-adjust")):
            exact.add(sel)
    out = []
    seen = set()
    for sel, decls, _ in rl:
        bg = (decls.get("background") or decls.get("background-color") or "").lower()
        if not bg or bg.startswith("#fff") or bg in ("white", "transparent", "none"):
            continue
        if sel in exact or sel in seen:
            continue
        seen.add(sel)
        out.append(Finding(id=f"print_color:{sel}", severity="soft", selector=sel,
                           message=f"{sel} sets background {bg} without "
                                   "print-color-adjust: exact; Chrome drops it on paper",
                           suggested_fix=f"add print-color-adjust:exact to {sel} in @media print"))
    return out
