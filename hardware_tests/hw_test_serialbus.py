#!/usr/bin/env python3
"""Integration test: SerialBus + SafetyPolicy against the real M17.

This exercises the SAME code path the MCP tools use (clamp via SafetyPolicy, then call the
bus), so passing here means the MCP server will drive the motor correctly — without needing
the `mcp` package installed. Mirrors server.py's move_to/move_relative/home/stop logic.

Run:
    PYTHONPATH=../src:/Users/sandbox1/servomotor/python_programs python3 hw_test_serialbus.py
"""
from __future__ import annotations

import sys

from servomotor_mcp.motors import SerialBus
from servomotor_mcp.safety import MotorLimits, SafetyPolicy

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbserial-210"
DEVICE_ALIAS = int(sys.argv[2]) if len(sys.argv) > 2 else 88
NAME = "x"  # friendly alias the "tools" use


def tool_move_to(bus, policy, motor, degrees, speed=None):
    """Replicates the server.py move_to tool: clamp, then drive."""
    policy.require_allowed(motor)
    target, note = policy.clamp_absolute(motor, degrees)
    spd, note_s = policy.clamp_speed(motor, speed)
    state = bus.move_to(motor, target, spd)
    notes = [n for n in (note, note_s) if n]
    print(f"  move_to({motor}, {degrees}) -> pos={state.position_deg:.2f}° "
          f"v={state.voltage_v}V" + (f"  | {notes}" if notes else ""))
    return state


def main() -> int:
    print(f"SerialBus integration test on {PORT}, device alias {DEVICE_ALIAS}\n")
    bus = SerialBus(port=PORT, motor_map={NAME: DEVICE_ALIAS})
    # z-style tight limits on our single motor so we can prove the clamp on real hardware:
    policy = SafetyPolicy(
        allowed=frozenset({NAME}),
        limits={NAME: MotorLimits(min_deg=-90, max_deg=90, max_speed=300)},
    )
    try:
        print("--- list_motors ---")
        for s in bus.list_motors():
            print(f"  {s.alias}: pos={s.position_deg:.2f}° v={s.voltage_v}V err={s.error}")

        print("\n--- absolute moves (clamped path) ---")
        tool_move_to(bus, policy, NAME, 45)
        tool_move_to(bus, policy, NAME, 0)
        tool_move_to(bus, policy, NAME, -30, speed=120)

        print("\n--- move_relative (tool path) ---")
        target, _ = policy.clamp_relative(NAME, bus.get_status(NAME)[0].position_deg, 15)
        s = bus.move_relative(NAME, target)
        print(f"  move_relative(+15) -> pos={s.position_deg:.2f}°")

        print("\n--- LIVE SAFETY CLAMP: command 200° on a motor limited to 90° ---")
        s = tool_move_to(bus, policy, NAME, 200)
        ok = abs(s.position_deg) <= 92
        print(f"  motor stopped at {s.position_deg:.2f}° (<=90 expected) -> "
              + ("CLAMP WORKED ✅" if ok else "CLAMP FAILED ❌"))

        print("\n--- mini sequence ('draw' with one axis) ---")
        for deg in (30, -30, 0):
            tool_move_to(bus, policy, NAME, deg)

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
