"""Safety-rail tests. These run with no hardware and no MCP SDK installed."""

import pytest

from servomotor_mcp.safety import MotorLimits, SafetyError, SafetyPolicy


def policy() -> SafetyPolicy:
    return SafetyPolicy(
        allowed=frozenset({"x", "y"}),
        limits={"x": MotorLimits(min_deg=-180, max_deg=180, max_speed=300)},
    )


def test_disallowed_motor_is_refused():
    with pytest.raises(SafetyError):
        policy().require_allowed("z")


def test_allowed_motor_passes():
    assert policy().require_allowed("x") == "x"


def test_absolute_target_clamped_to_range():
    value, note = policy().clamp_absolute("x", 500)
    assert value == 180
    assert note is not None and "clamped" in note


def test_absolute_target_within_range_unchanged():
    value, note = policy().clamp_absolute("x", 90)
    assert value == 90
    assert note is None


def test_relative_move_clamped_so_position_stays_in_range():
    # current 170, +50 would land at 220 -> clamp delta to +10 (target 180)
    delta, note = policy().clamp_relative("x", current_deg=170, delta_deg=50)
    assert delta == 10
    assert note is not None


def test_speed_clamped_to_max():
    spd, note = policy().clamp_speed("x", 9999)
    assert spd == 300
    assert note is not None


def test_unconfigured_motor_uses_default_limits():
    # 'y' has no explicit entry -> default range (-360..360), speed 360
    value, note = policy().clamp_absolute("y", 400)
    assert value == 360
    assert note is not None


def test_from_env_parses_limits(monkeypatch):
    monkeypatch.setenv("GEAROTONS_LIMITS", '{"x": {"min_deg": -90, "max_deg": 90, "max_speed": 100}}')
    p = SafetyPolicy.from_env(allowed_aliases=("x",))
    assert p.limits_for("x").max_deg == 90
    assert p.clamp_speed("x", 250)[0] == 100


def test_from_env_rejects_bad_json(monkeypatch):
    monkeypatch.setenv("GEAROTONS_LIMITS", "{not json}")
    with pytest.raises(SafetyError):
        SafetyPolicy.from_env(allowed_aliases=("x",))
