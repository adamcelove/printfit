import math

import pytest

from printfit import geom2d as G

SQ = [(0, 0), (10, 0), (10, 10), (0, 10)]
TRI = [(0, 0), (10, 4), (0, 8)]   # base x=0 from y 0..8, tip (10,4)


def shift(poly, dx, dy):
    return [(x + dx, y + dy) for x, y in poly]


def test_sat_separated_and_touching_are_none():
    assert G.sat_overlap(SQ, shift(SQ, 20, 0)) is None
    assert G.sat_overlap(SQ, shift(SQ, 10, 0)) is None


def test_sat_depth_and_push_axis():
    depth, ax = G.sat_overlap(SQ, shift(SQ, 7, 1))
    assert depth == pytest.approx(3)
    assert ax == pytest.approx((-1, 0))     # push SQ left, away from the other


def test_sat_rotated_square():
    c, s = math.cos(math.pi / 4), math.sin(math.pi / 4)
    diamond = [(5 + 5 * (x * c - y * s), 5 + 5 * (x * s + y * c)) for x, y in [(-1, -1), (1, -1), (1, 1), (-1, 1)]]
    assert G.sat_overlap(SQ, diamond) is not None
    assert G.sat_overlap(shift(SQ, 30, 30), diamond) is None


def test_convex_hull_drops_interior_points():
    h = G.convex_hull(SQ + [(5, 5), (2, 3)])
    assert sorted(h) == sorted(SQ)


def test_segment_rect():
    r = G.segment_rect((0, 0), (10, 0), 1.2)
    assert sorted(r) == pytest.approx(sorted([(0, 1.2), (10, 1.2), (10, -1.2), (0, -1.2)]))
    assert G.segment_rect((3, 3), (3, 3), 1) is None


def test_inset_quad_and_clamp():
    assert G.inset_quad(SQ, 1) == pytest.approx([(1, 1), (9, 1), (9, 9), (1, 9)])
    thin = [(0, 0), (10, 0), (10, 1), (0, 1)]
    q = G.inset_quad(thin, 3)
    assert q[3][1] - q[0][1] > 0           # never inverts


def test_cross_halfwidth_triangle():
    assert G.cross_halfwidth(TRI, (0, 4), (1, 0), 0.0) == pytest.approx(4)
    assert G.cross_halfwidth(TRI, (0, 4), (1, 0), 5.0) == pytest.approx(2)
    assert G.cross_halfwidth(TRI, (0, 4), (1, 0), 10.0) == pytest.approx(0, abs=1e-9)
    assert G.cross_halfwidth(TRI, (0, 4), (1, 0), 11.0) == 0.0
    assert G.cross_halfwidth(TRI, (0, 4), (1, 0), -1.0) == 0.0


def test_cross_halfwidth_off_axis_is_symmetric_part():
    # axis at y=2 inside a triangle spanning y 0..8 at the base: symmetric part is 2
    assert G.cross_halfwidth(TRI, (0, 2), (1, 0), 0.0) == pytest.approx(2)


def test_sat_pushes_thin_segment_uses_clearance_not_intersection():
    box = [(0, 0), (10, 0), (10, 10), (0, 10)]
    line = G.segment_rect((-20, 5), (30, 5), 1.0)    # y 4..6, crosses the whole box
    pushes = G.sat_pushes(box, line)
    # intersection length is 2 (the line's width), but separating needs 6 either way vertically
    assert G.sat_overlap(box, line)[0] == pytest.approx(2)
    d, ax = pushes[0]
    assert d == pytest.approx(6)
    assert abs(ax[0]) == pytest.approx(0) and abs(ax[1]) == pytest.approx(1)
    assert pushes[1][0] == pytest.approx(6) and pushes[1][1][1] == pytest.approx(-ax[1])
    assert [p[0] for p in pushes] == sorted(p[0] for p in pushes)
    assert len(pushes) == 4                           # parallel axes deduplicated


def test_sat_pushes_corner_overlap_matches_sat_overlap():
    other = shift(SQ, 7, 4)
    d, ax = G.sat_pushes(SQ, other)[0]
    depth, sax = G.sat_overlap(SQ, other)
    assert d == pytest.approx(depth) == pytest.approx(3)
    assert ax == pytest.approx(sax)
    assert ax == pytest.approx((-1, 0))


def test_sat_pushes_separated_and_touching_are_empty():
    assert G.sat_pushes(SQ, shift(SQ, 20, 0)) == []
    assert G.sat_pushes(SQ, shift(SQ, 10, 0)) == []
