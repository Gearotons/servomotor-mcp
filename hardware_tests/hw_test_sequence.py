#!/usr/bin/env python3
"""Hardware test of the run_sequence engine against the real M17.

This is the code path behind the "draw a square" / "wave" MCP tool — verified on hardware,
including a sequence-level safety clamp and an abort-on-disallowed-motor.

Run:
    PYTHONPATH=../src:/Users/sandbox1/servomotor/python_programs python3 hw_test_sequence.py
"""
from __future__ import annotations

import sys

from servomotor_mcp.motors import SerialBus
from servomotor_mcp.safety import MotorLimits, SafetyPolicy
from servomotor_mcp.sequencer import run_sequence_steps

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbserial-210"
DEVICE_ALIAS = int(sys.argv[2]) if len(sys.argv) > 2 else 88
NAME = "x"


def main() -> int:
    bus = SerialBus(port=PORT, motor_map={NAME: DEVICE_ALIAS})
    policy = SafetyPolicy(
        allowed=frozenset({NAME}),
        limits={NAME: MotorLimits(min_deg=-90, max_deg=90, max_speed=300)},
    )
    try:
        print("--- sequence 1: a 'draw' routine (home -> sweep -> back) ---")
        seq = [
            {"action": "home", "motor": NAME},
            {"action": "trapezoid_move", "motor": NAME, "degrees": 60, "duration_s": 0.8},
            {"action": "trapezoid_move", "motor": NAME, "degrees": -60, "duration_s": 0.8},
            {"action": "move_to", "motor": NAME, "degrees": 0, "speed": 180},
        ]
        notes = run_sequence_steps(bus, policy, seq)
        pos = bus.get_status(NAME)[0].position_deg
        print(f"  final pos={pos:.2f}°  notes={notes}")
        assert abs(pos) < 1.0, "should end near 0"

        print("\n--- sequence 2: sequence-level safety clamp (a step asks for 200°) ---")
        notes = run_sequence_steps(bus, policy, [
            {"action": "move_to", "motor": NAME, "degrees": 200},  # -> clamps to 90
            {"action": "move_to", "motor": NAME, "degrees": 0},
        ])
        print(f"  notes={notes}")
        assert any("clamped" in n for n in notes), "expected a clamp note"
        assert abs(bus.get_status(NAME)[0].position_deg) < 1.0

        print("\n--- sequence 3: abort on a disallowed motor ---")
        notes = run_sequence_steps(bus, policy, [
            {"action": "move_to", "motor": NAME, "degrees": 25},
            {"action": "move_to", "motor": "z", "degrees": 10},   # not allowed -> abort
            {"action": "move_to", "motor": NAME, "degrees": 80},  # must NOT run
        ])
        pos = bus.get_status(NAME)[0].position_deg
        print(f"  notes={notes}  final pos={pos:.2f}° (should be ~25, third step skipped)")
        assert any("aborted" in n for n in notes)
        assert abs(pos - 25) < 1.0

        bus.move_to(NAME, 0)
        print("\nSEQUENCE HARDWARE TEST PASSED")
        return 0
    except Exception as exc:
        print(f"\nSEQUENCE TEST FAILED: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        bus.close()
        print("  bus closed")


if __name__ == "__main__":
    raise SystemExit(main())
