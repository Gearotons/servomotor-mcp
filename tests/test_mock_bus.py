"""MockBus tests — verify the simulated daisy-chain behaves like real motor intents."""

import pytest

from servomotor_mcp.motors import MockBus, get_bus


def test_lists_configured_motors():
    bus = MockBus(aliases=("x", "y", "z"))
    aliases = {m.alias for m in bus.list_motors()}
    assert aliases == {"x", "y", "z"}


def test_move_to_sets_absolute_position():
    bus = MockBus(aliases=("x",))
    state = bus.move_to("x", 90)
    assert state.position_deg == 90
    assert bus.get_status("x")[0].position_deg == 90


def test_move_relative_accumulates():
    bus = MockBus(aliases=("x",))
    bus.move_to("x", 10)
    bus.move_relative("x", 5)
    bus.move_relative("x", -3)
    assert bus.get_status("x")[0].position_deg == 12


def test_home_all_zeroes_every_motor():
    bus = MockBus(aliases=("x", "y"))
    bus.move_to("x", 30)
    bus.move_to("y", -40)
    bus.home()
    assert all(m.position_deg == 0 for m in bus.get_status())


def test_unknown_motor_raises():
    bus = MockBus(aliases=("x",))
    with pytest.raises(KeyError):
        bus.move_to("nope", 10)


def test_actions_are_logged():
    bus = MockBus(aliases=("x",))
    bus.move_to("x", 45)
    bus.home("x")
    assert any("move_to" in line for line in bus.log)
    assert any("home" in line for line in bus.log)


def test_reset_returns_status_and_logs():
    bus = MockBus(aliases=("x", "y"))
    states = bus.reset()
    assert {s.alias for s in states} == {"x", "y"}
    assert any("reset" in line for line in bus.log)


def test_get_bus_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("GEAROTONS_MOTOR_BACKEND", raising=False)
    monkeypatch.setenv("GEAROTONS_MOTOR_ALIASES", "a,b")
    bus = get_bus()
    assert isinstance(bus, MockBus)
    assert {m.alias for m in bus.list_motors()} == {"a", "b"}
