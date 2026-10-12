import dataclasses

from printfit import types as T


def test_only_hard_fails():
    for sev, exp in (("hard", True), ("soft", False), ("info", False)):
        assert T.Finding(id="x:y", severity=sev, message="").failed is exp


def test_role_limits_cover_every_role():
    roles = set(T.FigRole.__args__)
    assert set(T.ROLE_LIMITS) == roles


def test_soft_checks_not_in_hard_gates():
    for name in ("figure_height", "aspect_ratio", "qa_split", "fill_ratio"):
        assert name not in T.HARD_GATES


def test_no_hard_aspect_ratio():
    assert not any(v.aspect_ratio_hard for v in T.ROLE_LIMITS.values())


def test_length_fields_end_in_px():
    for cls in (T.Finding, T.PageMetrics, T.RenderArtifacts):
        for f in dataclasses.fields(cls):
            assert not f.name.endswith("_pt"), f.name
            if any(k in f.name for k in ("height", "width", "slack", "paper")):
                assert f.name.endswith("_px") or f.name.endswith("_paths"), f.name
