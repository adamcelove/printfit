import pytest

from printfit import profile
from printfit.types import ProfileError


def test_precedence():
    p = {"roles": {"grid": "graph", "g-nl": "scale"}}
    assert profile.role_for(["grid", "g-nl"], None, p) == "scale"
    assert profile.role_for(["grid"], "diagram", p) == "diagram"
    assert profile.role_for(["zzz"], None, p) == "unknown"
    assert profile.limits_for("unknown", p).aspect_ratio_hard is False


def test_role_limit_override_merges():
    p = {"role_limits": {"diagram": {"height_frac_max": 0.55}}}
    lim = profile.limits_for("diagram", p)
    assert lim.height_frac_max == 0.55 and lim.aspect_ratio_max == 3.5


def test_unknown_key_is_error(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text("schema: 1\nname: x\nrole_limts: {}\n")
    with pytest.raises(ProfileError):
        profile.load(str(f))


def test_load_defaults(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text("schema: 1\nname: x\nroles:\n  grid: graph\n")
    p = profile.load(str(f))
    assert p["fill"]["skip_final_page"] is True
    assert p["roles"] == {"grid": "graph"}


def test_mark_roles_validated(tmp_path):
    import pytest
    from printfit import profile as P
    from printfit.types import ProfileError
    p = tmp_path / "p.yaml"
    p.write_text("mark_roles:\n  ax: axis\n")
    assert P.load(str(p))["mark_roles"] == {"ax": "axis"}
    p.write_text("mark_roles:\n  ax: fence\n")
    with pytest.raises(ProfileError, match="mark_roles.ax"):
        P.load(str(p))
    assert P.load(None)["mark_roles"] == {}
