"""Convex 2-D geometry for the figure-mark gates. Pure functions over
(x, y) tuples in page px; figures hold at most a few thousand points, so
plain Python is fast enough and keeps every case unit-testable."""
from __future__ import annotations

import math

Pt = tuple[float, float]
Poly = list[Pt]


def sub(a: Pt, b: Pt) -> Pt:
    return (a[0] - b[0], a[1] - b[1])


def dot(a: Pt, b: Pt) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _unit(v: Pt) -> Pt:
    n = math.hypot(*v)
    return (v[0] / n, v[1] / n) if n else (0.0, 0.0)


def _cross(o: Pt, a: Pt, b: Pt) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def convex_hull(pts) -> Poly:
    ps = sorted(set((float(x), float(y)) for x, y in pts))
    if len(ps) <= 2:
        return ps
    lower: Poly = []
    for p in ps:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: Poly = []
    for p in reversed(ps):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _centroid(poly: Poly) -> Pt:
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))


def sat_overlap(a: Poly, b: Poly) -> tuple[float, Pt] | None:
    best: tuple[float, Pt] | None = None
    for poly in (a, b):
        n = len(poly)
        for i in range(n):
            e = sub(poly[(i + 1) % n], poly[i])
            if e == (0.0, 0.0) or e == (0, 0):
                continue
            ax = _unit((-e[1], e[0]))
            pa = [dot(p, ax) for p in a]
            pb = [dot(p, ax) for p in b]
            o = min(max(pa), max(pb)) - max(min(pa), min(pb))
            if o <= 1e-9:
                return None
            if best is None or o < best[0]:
                best = (o, ax)
    if best is None:
        return None
    o, ax = best
    if dot(sub(_centroid(a), _centroid(b)), ax) < 0:
        ax = (-ax[0], -ax[1])
    return o, ax


def segment_rect(p: Pt, q: Pt, half_w: float) -> Poly | None:
    d = sub(q, p)
    length = math.hypot(*d)
    if length < 1e-9:
        return None
    u = (d[0] / length, d[1] / length)
    n = (-u[1] * half_w, u[0] * half_w)
    return [(p[0] + n[0], p[1] + n[1]), (q[0] + n[0], q[1] + n[1]),
            (q[0] - n[0], q[1] - n[1]), (p[0] - n[0], p[1] - n[1])]


def inset_quad(quad: Poly, d: float) -> Poly:
    c0, c1, c2, c3 = quad
    w, h = math.hypot(*sub(c1, c0)), math.hypot(*sub(c3, c0))
    d = max(0.0, min(d, w / 2 - 0.01, h / 2 - 0.01))
    u, v = _unit(sub(c1, c0)), _unit(sub(c3, c0))
    return [(c0[0] + d * u[0] + d * v[0], c0[1] + d * u[1] + d * v[1]),
            (c1[0] - d * u[0] + d * v[0], c1[1] - d * u[1] + d * v[1]),
            (c2[0] - d * u[0] - d * v[0], c2[1] - d * u[1] - d * v[1]),
            (c3[0] + d * u[0] - d * v[0], c3[1] + d * u[1] - d * v[1])]


def cross_halfwidth(poly: Poly, origin: Pt, axis: Pt, s: float) -> float:
    perp = (-axis[1], axis[0])
    c = (origin[0] + s * axis[0], origin[1] + s * axis[1])
    ts: list[float] = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        sa, sb = dot(sub(a, c), axis), dot(sub(b, c), axis)
        if (sa > 1e-12 and sb > 1e-12) or (sa < -1e-12 and sb < -1e-12):
            continue
        if abs(sa - sb) < 1e-12:
            ts += [dot(sub(a, c), perp), dot(sub(b, c), perp)]
            continue
        t = sa / (sa - sb)
        x = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        ts.append(dot(sub(x, c), perp))
    if len(ts) < 2:
        return 0.0
    lo, hi = min(ts), max(ts)
    if lo > 0 or hi < 0:
        return 0.0
    return min(hi, -lo)
