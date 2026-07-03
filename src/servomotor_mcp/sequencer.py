"""Choreographed-sequence execution — pure, testable, no MCP dependency.

`run_sequence_steps` is the engine behind the `run_sequence` MCP tool ("draw a square",
"wave"). It lives here (not in server.py) so it can be unit-tested with the mock backend
and hardware-tested with a real motor without importing the `mcp` SDK. Steps are forwarded
straight to the bus, in order.

Step shapes:
    {"action": "move_to",       "motor": "88", "degrees": 90, "speed_dps": 120}
    {"action": "move_relative", "motor": "88", "degrees": -30}
    {"action": "stop"}                                   # motor optional -> all
    {"action": "wait",          "seconds": 0.5}
    {"action": "command",       "motor": "88", "name": "vibrate", "params": [1]}

"command" runs any command from the library catalog by tool name (params positional,
same order as the generated tool's parameters).
"""

from __future__ import annotations

import time


def run_sequence_steps(bus, steps: list[dict]) -> None:
    """Execute steps in order. Raises ``ValueError`` on an unknown action."""
    for i, step in enumerate(steps):
        action = step.get("action")
        motor = step.get("motor")
        if action == "move_to":
            bus.move_to(motor, float(step["degrees"]), step.get("speed_dps") or step.get("speed"))
        elif action == "move_relative":
            bus.move_relative(motor, float(step["degrees"]), step.get("speed_dps") or step.get("speed"))
        elif action == "stop":
            bus.stop(motor)
        elif action == "wait":
            time.sleep(max(0.0, float(step.get("seconds", 0))))
        elif action == "command":
            bus.execute(motor, step["name"], list(step.get("params", [])))
        else:
            raise ValueError(f"step {i}: unknown action {action!r}")
