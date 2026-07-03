"""Sequence engine against the mock backend."""

import pytest

from servomotor_mcp.motors import MockBus
from servomotor_mcp.sequencer import run_sequence_steps


@pytest.fixture()
def bus():
    b = MockBus()
    b.connect(port="MOCK0")
    return b


def test_square_wave_sequence(bus):
    run_sequence_steps(bus, [
        {"action": "move_to", "motor": "42", "degrees": 90, "speed_dps": 120},
        {"action": "move_relative", "motor": "42", "degrees": -30},
        {"action": "wait", "seconds": 0},
        {"action": "move_to", "motor": "43", "degrees": 720},  # multi-turn passthrough
        {"action": "stop"},
    ])
    assert bus.motor_status("42")["position_deg"] == 60.0
    assert bus.motor_status("43")["position_deg"] == 720.0


def test_raw_command_step(bus):
    run_sequence_steps(bus, [
        {"action": "command", "motor": "42", "name": "zero_position", "params": []},
        {"action": "command", "motor": "42", "name": "enable_mosfets", "params": []},
        {"action": "command", "motor": "42", "name": "go_to_position", "params": [45, 1.0]},
    ])
    assert bus.motor_status("42")["position_deg"] == 45.0


def test_unknown_action_raises(bus):
    with pytest.raises(ValueError, match="unknown action"):
        run_sequence_steps(bus, [{"action": "teleport"}])
