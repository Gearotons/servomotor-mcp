"""Sequencer tests on the mock backend (no hardware, no mcp)."""

import pytest

from servomotor_mcp.motors import MockBus
from servomotor_mcp.sequencer import run_sequence_steps


def test_sequence_runs_in_order():
    bus = MockBus(aliases=("x", "y"))
    run_sequence_steps(bus, [
        {"action": "move_to", "motor": "x", "degrees": 45},
        {"action": "move_to", "motor": "y", "degrees": 30},
        {"action": "move_relative", "motor": "x", "degrees": -10},
    ])
    assert bus.get_status("x")[0].position_deg == 35
    assert bus.get_status("y")[0].position_deg == 30


def test_sequence_allows_full_multiturn_moves():
    # No clamping: a multi-turn target is executed as-is.
    bus = MockBus(aliases=("x",))
    run_sequence_steps(bus, [{"action": "move_to", "motor": "x", "degrees": 720}])
    assert bus.get_status("x")[0].position_deg == 720


def test_unknown_action_raises():
    bus = MockBus(aliases=("x",))
    with pytest.raises(ValueError, match="unknown action"):
        run_sequence_steps(bus, [{"action": "fly", "motor": "x"}])


def test_home_and_stop_steps():
    bus = MockBus(aliases=("x", "y"))
    run_sequence_steps(bus, [
        {"action": "move_to", "motor": "x", "degrees": 50},
        {"action": "home"},
        {"action": "stop"},
    ])
    assert all(m.position_deg == 0 for m in bus.get_status())
