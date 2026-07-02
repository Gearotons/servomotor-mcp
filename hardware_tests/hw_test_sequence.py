#!/usr/bin/env python3
"""Hardware test of the run_sequence engine against the real M17.

This is the code path behind the "draw a square" / "wave" MCP tool — verified on hardware.
The MCP is a thin control layer: steps are forwarded straight to the bus with no software
clamping (the motor's firmware self-protects OC/OV/OT), so a full-range multi-turn move
reaches its commanded target.

Run:
    PYTHONPATH=../src:/Users/sandbox1/servomotor/python_programs python3 hw_test_sequence.py
"""
from __future__ import annotations

import sys

from servomotor_mcp.motors import SerialBus
from servomotor_mcp.sequencer import run_sequence_steps

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbserial-210"
DEVICE_ALIAS = int(sys.argv[2]) if len(sys.argv) > 2 else 88
NAME = "x"


def main() -> int:
    bus = SerialBus(port=PORT, motor_map={NAME: DEVICE_ALIAS})
    try:
        print("--- sequence 1: a 'draw' routine (home -> sweep -> back) ---")
        seq = [
            {"action": "home", "motor": NAME},
            {"action": "trapezoid_move", "motor": NAME, "degrees": 60, "duration_s": 0.8},
            {"action": "trapezoid_move", "motor": NAME, "degrees": -60, "duration_s": 0.8},
            {"action": "move_to", "motor": NAME, "degrees": 0, "speed": 180},
        ]
        run_sequence_steps(bus, seq)
        pos = bus.get_status(NAME)[0].position_deg
        print(f"  final pos={pos:.2f}°")
        assert abs(pos) < 1.0, "should end near 0"

        print("\n--- sequence 2: full-range multi-turn move (no clamp, thin layer) ---")
        run_sequence_steps(bus, [
            {"action": "move_to", "motor": NAME, "degrees": 720},  # two full turns
        ])
        pos = bus.get_status(NAME)[0].position_deg
        print(f"  commanded 720° -> pos={pos:.2f}° (should reach ~720, no clamp)")
        assert abs(pos - 720) < 2.0, "commanded 720° should reach ~720° (no software clamp)"
        run_sequence_steps(bus, [{"action": "move_to", "motor": NAME, "degrees": 0}])
        assert abs(bus.get_status(NAME)[0].position_deg) < 1.0

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
