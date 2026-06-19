"""Choreographed-sequence execution — pure, testable, no MCP dependency.

`run_sequence_steps` is the engine behind the `run_sequence` MCP tool ("draw a square",
"wave"). It lives here (not in server.py) so it can be unit-tested with the mock backend
and hardware-tested with a real motor without importing the `mcp` SDK. Each step is
individually safety-checked + clamped; an unsafe step aborts the sequence rather than
charging ahead.

Step shapes:
    {"action": "move_to",        "motor": "x", "degrees": 90, "speed": 120}
    {"action": "move_relative",  "motor": "y", "degrees": -30}
    {"action": "trapezoid_move", "motor": "z", "degrees": 45, "duration_s": 1.5}
    {"action": "home",           "motor": "x"}     # motor optional -> all
    {"action": "stop"}                              # motor optional -> all
"""

from __future__ import annotations

from .safety import SafetyError, SafetyPolicy


def clamped_move_to(bus, policy: SafetyPolicy, motor, degrees, speed=None) -> list[str]:
    policy.require_allowed(motor)
    target, n1 = policy.clamp_absolute(motor, degrees)
    spd, n2 = policy.clamp_speed(motor, speed)
    bus.move_to(motor, target, spd)
    return [n for n in (n1, n2) if n]


def clamped_move_relative(bus, policy: SafetyPolicy, motor, degrees, speed=None) -> list[str]:
    policy.require_allowed(motor)
    current = bus.get_status(motor)[0].position_deg
    delta, n1 = policy.clamp_relative(motor, current, degrees)
    spd, n2 = policy.clamp_speed(motor, speed)
    bus.move_relative(motor, delta, spd)
    return [n for n in (n1, n2) if n]


def clamped_trapezoid(bus, policy: SafetyPolicy, motor, degrees, duration_s) -> list[str]:
    policy.require_allowed(motor)
    target, n1 = policy.clamp_absolute(motor, degrees)
    bus.trapezoid_move(motor, target, duration_s)
    return [n for n in (n1,) if n]


def run_sequence_steps(bus, policy: SafetyPolicy, steps: list[dict]) -> list[str]:
    """Execute steps in order; return the list of safety notes that fired.

    Stops at the first unsafe step (appends an 'aborted' note) rather than continuing.
    """
    notes: list[str] = []
    for i, step in enumerate(steps):
        action = step.get("action")
        motor = step.get("motor")
        try:
            if action == "move_to":
                notes += clamped_move_to(bus, policy, motor, float(step["degrees"]), step.get("speed"))
            elif action == "move_relative":
                notes += clamped_move_relative(bus, policy, motor, float(step["degrees"]), step.get("speed"))
            elif action == "trapezoid_move":
                notes += clamped_trapezoid(bus, policy, motor, float(step["degrees"]), float(step["duration_s"]))
            elif action == "home":
                if motor is not None:
                    policy.require_allowed(motor)
                bus.home(motor)
            elif action == "stop":
                if motor is not None:
                    policy.require_allowed(motor)
                bus.stop(motor)
            else:
                raise SafetyError(f"step {i}: unknown action {action!r}")
        except SafetyError as exc:
            notes.append(f"step {i} aborted: {exc}")
            break
    return notes
