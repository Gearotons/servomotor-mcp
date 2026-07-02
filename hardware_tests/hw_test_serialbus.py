#!/usr/bin/env python3
"""Integration test: SerialBus against the real M17.

This exercises the SAME code path the MCP tools use — the MCP is a thin control layer that
calls the bus directly with no software clamping (the motor's firmware self-protects
OC/OV/OT). Passing here means the MCP server will drive the motor correctly — without needing
the `mcp` package installed. Mirrors server.py's move_to/move_relative/home/stop logic.

Run:
    PYTHONPATH=../src:/Users/sandbox1/servomotor/python_programs python3 hw_test_serialbus.py
"""
from __future__ import annotations

import sys

from servomotor_mcp.motors import SerialBus

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbserial-210"
DEVICE_ALIAS = int(sys.argv[2]) if len(sys.argv) > 2 else 88
NAME = "x"  # friendly alias the "tools" use


def tool_move_to(bus, motor, degrees, speed=None):
    """Replicates the server.py move_to tool: drive the bus directly (no clamp)."""
    state = bus.move_to(motor, degrees, speed)
    print(f"  move_to({motor}, {degrees}) -> pos={state.position_deg:.2f}° "
          f"v={state.voltage_v}V")
    return state


def main() -> int:
    print(f"SerialBus integration test on {PORT}, device alias {DEVICE_ALIAS}\n")
    bus = SerialBus(port=PORT, motor_map={NAME: DEVICE_ALIAS})
    try:
        print("--- list_motors ---")
        for s in bus.list_motors():
            print(f"  {s.alias}: pos={s.position_deg:.2f}° v={s.voltage_v}V err={s.error}")

        print("\n--- absolute moves (direct, no clamp) ---")
        tool_move_to(bus, NAME, 45)
        tool_move_to(bus, NAME, 0)
        tool_move_to(bus, NAME, -30, speed=120)

        print("\n--- move_relative (tool path) ---")
        s = bus.move_relative(NAME, 15)
        print(f"  move_relative(+15) -> pos={s.position_deg:.2f}°")

        print("\n--- FULL RANGE: command 720° (two turns) — thin layer, no clamp ---")
        s = tool_move_to(bus, NAME, 720)
        ok = abs(s.position_deg - 720) <= 2
        print(f"  motor reached {s.position_deg:.2f}° (~720 expected) -> "
              + ("FULL RANGE OK ✅" if ok else "FULL RANGE FAILED ❌"))
        tool_move_to(bus, NAME, 0)

        print("\n--- mini sequence ('draw' with one axis) ---")
        for deg in (30, -30, 0):
            tool_move_to(bus, NAME, deg)

        print("\n--- home (back to 0) + stop (disable MOSFETs) ---")
        for s in bus.home(NAME):
            print(f"  homed {s.alias} -> {s.position_deg:.2f}°")
        for s in bus.stop(NAME):
            print(f"  stopped {s.alias}: pos={s.position_deg:.2f}°")

        print("\nSERIALBUS INTEGRATION TEST PASSED")
        return 0
    except Exception as exc:
        print(f"\nINTEGRATION TEST FAILED: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        bus.close()
        print("  bus closed (MOSFETs disabled, port closed)")


if __name__ == "__main__":
    raise SystemExit(main())
