"""Choreographed-sequence execution — pure, testable, no MCP dependency.

`run_sequence_steps` is the engine behind the `run_sequence` MCP tool ("draw a square",
"wave"). It lives here (not in server.py) so it can be unit-tested with the mock backend
and hardware-tested with a real motor without importing the `mcp` SDK. Steps are forwarded
straight to the bus, in order.

Step shapes:
    {"action": "move_to",        "motor": "x", "degrees": 90, "speed": 120}
    {"action": "move_relative",  "motor": "y", "degrees": -30}
    {"action": "trapezoid_move", "motor": "z", "degrees": 45, "duration_s": 1.5}
    {"action": "home",           "motor": "x"}     # motor optional -> all
    {"action": "stop"}                              # motor optional -> all
"""

from __future__ import annotations


def run_sequence_steps(bus, steps: list[dict]) -> None:
    """Execute steps in order. Raises ``ValueError`` on an unknown action."""
    for i, step in enumerate(steps):
        action = step.get("action")
        motor = step.get("motor")
        if action == "move_to":
            bus.move_to(motor, float(step["degrees"]), step.get("speed"))
        elif action == "move_relative":
            bus.move_relative(motor, float(step["degrees"]), step.get("speed"))
        elif action == "trapezoid_move":
            bus.trapezoid_move(motor, float(step["degrees"]), float(step["duration_s"]))
        elif action == "home":
            bus.home(motor)
        elif action == "stop":
            bus.stop(motor)
        else:
            raise ValueError(f"step {i}: unknown action {action!r}")
