"""Gearotons M17 — MCP server.

Exposes the M17 servomotor as a small set of high-level tools so any MCP-capable client
(Claude Desktop, Claude Code, an agent loop) can drive real motors from natural language.
Built on the official ``mcp`` Python SDK (FastMCP).

The server is a thin control layer: it maps friendly aliases to real motors and forwards
each tool call straight to the hardware. There is no software clamping — the motor executes
what it is asked to, exactly like driving it from the ``servomotor`` library directly. The
motor's own firmware protections (over-current / over-voltage / over-temperature) still apply.

Run locally (mock backend, no hardware):
    uvx --from . servomotor-mcp        # or: python -m servomotor_mcp

Point at real hardware:
    GEAROTONS_MOTOR_BACKEND=serial GEAROTONS_SERIAL_PORT=/dev/ttyUSB0 servomotor-mcp

Tool descriptions are deliberately prescriptive about *when* to call each tool — recent
models reach for tools conservatively, and a clear trigger condition in the description
measurably improves correct tool selection.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .motors import get_bus
from .sequencer import run_sequence_steps

mcp = FastMCP("gearotons-motor")

_bus = get_bus()


def _result(states) -> dict:
    """Uniform tool result: the affected motor states."""
    states = states if isinstance(states, list) else [states]
    return {"motors": [s.as_dict() for s in states]}


@mcp.tool()
def list_motors() -> dict:
    """List every motor on the RS-485 bus with its alias and current position.

    Call this FIRST in any session to discover what is connected before issuing moves.
    """
    return _result(_bus.list_motors())


@mcp.tool()
def move_to(motor: str, degrees: float, speed: float | None = None) -> dict:
    """Move one motor to an ABSOLUTE angle in degrees (closed-loop, won't lose steps).

    Use when the user names a target position ("go to 90 degrees", "point straight up").
    Angles are unbounded — full multi-turn travel is allowed (e.g. 360 = one full turn,
    720 = two). ``speed`` is degrees/second (optional).
    """
    return _result(_bus.move_to(motor, degrees, speed))


@mcp.tool()
def move_relative(motor: str, degrees: float, speed: float | None = None) -> dict:
    """Nudge one motor by a RELATIVE amount in degrees (+ / -).

    Use for "turn a bit more", "back off 10 degrees", or incremental jogging. Any magnitude
    is allowed; multiple full turns are fine.
    """
    return _result(_bus.move_relative(motor, degrees, speed))


@mcp.tool()
def trapezoid_move(motor: str, degrees: float, duration_s: float) -> dict:
    """Move to an absolute angle with smooth acceleration/deceleration over ``duration_s``.

    Prefer this over ``move_to`` for arms, plotters, or anything where a sudden move would
    jerk the mechanism. Good for choreographed motion.
    """
    return _result(_bus.trapezoid_move(motor, degrees, duration_s))


@mcp.tool()
def home(motor: str | None = None) -> dict:
    """Send one motor to absolute zero, or ALL motors if ``motor`` is omitted.

    Call at the start of a build, or when the user says "home", "reset", or "go to zero".
    """
    return _result(_bus.home(motor))


@mcp.tool()
def get_status(motor: str | None = None) -> dict:
    """Report position, motion state, voltage, and any error for one motor or all motors.

    Call after a move to CONFIRM it completed, or when the user asks "where is it / what's
    its state".
    """
    return _result(_bus.get_status(motor))


@mcp.tool()
def stop(motor: str | None = None) -> dict:
    """Immediately halt motion on one motor, or ALL motors if omitted.

    Use for "stop", "halt", "cancel", or any sign something is wrong. Always available.
    """
    return _result(_bus.stop(motor))


@mcp.tool()
def reset(motor: str | None = None) -> dict:
    """Recover a motor from a latched fault by issuing a firmware system reset (reboots ~2s).

    Call when ``get_status`` reports an error the motor won't clear on its own. The motor
    returns to a clean, idle state afterward. Omit ``motor`` to reset all.
    """
    return _result(_bus.reset(motor))


@mcp.tool()
def run_sequence(steps: list[dict]) -> dict:
    """Execute a choreographed sequence of moves, e.g. to "draw a square" or "wave".

    Each step is one of:
        {"action": "move_to",        "motor": "x", "degrees": 90, "speed": 120}
        {"action": "move_relative",  "motor": "y", "degrees": -30}
        {"action": "trapezoid_move", "motor": "z", "degrees": 45, "duration_s": 1.5}
        {"action": "home",           "motor": "x"}            # motor optional -> all
        {"action": "stop"}                                     # motor optional -> all

    Steps run in order. Returns the final state of every motor. Engine lives in
    ``sequencer.py`` (pure, unit- and hardware-tested without the MCP SDK).
    """
    run_sequence_steps(_bus, steps)
    return _result(_bus.get_status())


def main() -> None:
    """Entry point.

    Default transport is **stdio** — the local transport Claude Desktop / Claude Code /
    Cursor use to launch the server next to the motor. This is the normal, secure setup:
    the server runs on the same machine the motor is plugged into; nothing is exposed.

    To expose a motor *remotely* (e.g. behind a tunnel, for a demo), set
    ``GEAROTONS_MCP_TRANSPORT=http`` to serve a **Streamable-HTTP** endpoint at
    ``http://HOST:PORT/mcp``. Defaults bind to localhost (127.0.0.1) on purpose — put a
    tunnel/auth in front of it; never bind 0.0.0.0 straight to the internet without auth.
    See `content/ai-demo/integrations/publish-and-expose.md`.
    """
    import os

    transport = os.environ.get("GEAROTONS_MCP_TRANSPORT", "stdio").lower()
    if transport in ("http", "streamable-http", "streamable_http"):
        mcp.settings.host = os.environ.get("GEAROTONS_MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("GEAROTONS_MCP_PORT", "8808"))
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
