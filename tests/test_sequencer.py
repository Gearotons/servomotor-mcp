"""Sequencer tests on the mock backend (no hardware, no mcp)."""

from servomotor_mcp.motors import MockBus
from servomotor_mcp.safety import MotorLimits, SafetyPolicy
from servomotor_mcp.sequencer import run_sequence_steps


def setup():
    bus = MockBus(aliases=("x", "y"))
    policy = SafetyPolicy(
        allowed=frozenset({"x", "y"}),
        limits={"x": MotorLimits(min_deg=-90, max_deg=90, max_speed=300)},
    )
    return bus, policy


def test_sequence_runs_in_order_no_notes():
    bus, policy = setup()
    notes = run_sequence_steps(bus, policy, [
        {"action": "move_to", "motor": "x", "degrees": 45},
        {"action": "move_to", "motor": "y", "degrees": 30},
        {"action": "move_relative", "motor": "x", "degrees": -10},
    ])
    assert notes == []
    assert bus.get_status("x")[0].position_deg == 35
    assert bus.get_status("y")[0].position_deg == 30


def test_sequence_clamps_and_reports():
    bus, policy = setup()
    notes = run_sequence_steps(bus, policy, [
        {"action": "move_to", "motor": "x", "degrees": 200},
    ])
    assert bus.get_status("x")[0].position_deg == 90  # clamped
    assert any("clamped" in n for n in notes)


def test_sequence_aborts_on_disallowed_motor():
    bus, policy = setup()
    notes = run_sequence_steps(bus, policy, [
        {"action": "move_to", "motor": "x", "degrees": 20},
        {"action": "move_to", "motor": "z", "degrees": 10},   # not allowed -> abort
        {"action": "move_to", "motor": "x", "degrees": 80},   # must NOT run
    ])
    assert bus.get_status("x")[0].position_deg == 20  # third step never executed
    assert any("aborted" in n for n in notes)


def test_unknown_action_aborts():
    bus, policy = setup()
    notes = run_sequence_steps(bus, policy, [{"action": "fly", "motor": "x"}])
    assert any("aborted" in n and "unknown action" in n for n in notes)


def test_home_and_stop_steps():
    bus, policy = setup()
    run_sequence_steps(bus, policy, [
        {"action": "move_to", "motor": "x", "degrees": 50},
        {"action": "home"},
        {"action": "stop"},
    ])
    assert all(m.position_deg == 0 for m in bus.get_status())
