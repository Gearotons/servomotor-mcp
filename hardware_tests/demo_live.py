#!/usr/bin/env python3
"""Watchable demo: drive the real M17 through the MCP server's tool code path.

Prints each plain-language intent + the tool it maps to, then moves the motor with a pause
so you can watch. This is exactly what an AI assistant does via the MCP server — here a
script plays the role of the AI so you can see the motor respond. Ends with the safety clamp.

Run:
    PYTHONPATH=../src:/Users/sandbox1/servomotor/python_programs python3 demo_live.py
"""
from __future__ import annotations

import time

from servomotor_mcp.motors import SerialBus
from servomotor_mcp.safety import MotorLimits, SafetyPolicy

NAME = "x"
PAUSE = 1.2


def say(intent, tool):
    print(f'\n  🗣  "{intent}"\n      -> MCP tool: {tool}')


def main() -> int:
    bus = SerialBus(port="/dev/cu.usbserial-210", motor_map={NAME: 88})
    policy = SafetyPolicy(allowed=frozenset({NAME}),
                          limits={NAME: MotorLimits(min_deg=-90, max_deg=90, max_speed=300)})
    m = bus._m[NAME]
    try:
        print("=" * 64)
        print(" GEAROTONS M17 — live demo  (WATCH THE MOTOR)")
        print(" A script is standing in for the AI; it calls the same MCP tools.")
        print("=" * 64)

        say("Which motor are you?  (blink so I can see you)", "identify")
        m.identify(); print("      -> the motor's LED should be blinking now"); time.sleep(2.0)

        say("Home — go to zero.", "home()")
        bus.home(NAME); print(f"      -> position: {bus.get_status(NAME)[0].position_deg:.1f}°"); time.sleep(PAUSE)

        say("Point to 60 degrees.", "move_to(x, 60)")
        s = bus.move_to(NAME, 60); print(f"      -> position: {s.position_deg:.1f}°"); time.sleep(PAUSE)

        say("Now go to minus 60 degrees.", "move_to(x, -60)")
        s = bus.move_to(NAME, -60); print(f"      -> position: {s.position_deg:.1f}°"); time.sleep(PAUSE)

        say("Wave hello.", "run_sequence([...])")
        for deg in (25, -25, 18, -18, 0):
            bus.move_to(NAME, deg, speed=240)
        print(f"      -> back to {bus.get_status(NAME)[0].position_deg:.1f}°"); time.sleep(PAUSE)

        print("\n" + "-" * 64)
        print(" SAFETY DEMO — the limits live in the software, not the AI's goodwill.")
        print(" This motor is configured with a max of 90°.")
        say("Spin all the way to 300 degrees!", "move_to(x, 300)")
        target, note = policy.clamp_absolute(NAME, 300)
        s = bus.move_to(NAME, target)
        print(f"      -> {note}")
        print(f"      -> motor STOPPED at {s.position_deg:.1f}° (refused to exceed 90°)")
        time.sleep(PAUSE)

        say("Okay, home and rest.", "home() + stop()")
        bus.home(NAME); bus.stop(NAME)
        print(f"      -> position: {bus.get_status(NAME)[0].position_deg:.1f}°, motor released")

        print("\n" + "=" * 64)
        print(" Demo done. That's the MCP toolset driving your real motor.")
        print(" With the Python-3.10 setup, Claude calls these same tools from chat.")
        print("=" * 64)
        return 0
    finally:
        bus.close()


if __name__ == "__main__":
    raise SystemExit(main())
