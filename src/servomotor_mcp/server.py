"""Gearotons M17 — MCP server.

Drives Gearotons servomotors from natural language through any MCP client (Claude
Desktop, Claude Code, an agent loop). Built on the official ``mcp`` Python SDK (FastMCP).

Design:

- **Nothing about the setup is hardcoded.** The server starts disconnected. The model
  enumerates the machine's serial ports (``list_serial_ports``), opens one (``connect``),
  and the motors on that bus are discovered with the firmware's "Detect devices" command.
  The user can steer all of this in plain English ("use the adapter that mentions FTDI").
- **The full command set is exposed.** One MCP tool is generated for every command in the
  ``servomotor`` library's data-driven catalog (48 commands as of library 0.10.0), so
  anything the firmware can do, the model can do. New library commands appear here
  automatically. A few high-level convenience tools (``move_to``, ``move_relative``,
  ``run_sequence``…) wrap the common cases with speed/duration handling and completion
  waits.
- **Thin control layer.** No software clamping; the motor executes what it is asked to.
  The firmware's own protections (over-current / over-voltage / over-temperature) still
  apply.

Session recipe (also what the tool descriptions steer the model toward):
    list_serial_ports -> connect(port) -> [auto-detects motors] -> move/query tools

Works on macOS, Windows, and Linux — port names like ``/dev/cu.usbserial-*``, ``COM3``,
and ``/dev/ttyUSB0`` are all just strings from ``list_serial_ports``.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .catalog import UNITS, CommandSpec, load_catalog
from .motors import get_bus
from .sequencer import run_sequence_steps

mcp = FastMCP("gearotons-motor")

_bus = get_bus()

MOTOR_ARG_DOC = (
    'motor: an alias number (e.g. 88), a 16-hex-digit unique ID (e.g. "0123456789ABCDEF"), '
    'or "all" to broadcast to every motor on the bus (broadcasts get no responses back).'
)


# --------------------------------------------------------------------------------------
# Connection & discovery
# --------------------------------------------------------------------------------------

@mcp.tool()
def list_serial_ports() -> dict:
    """List the serial ports on this computer so one can be chosen for ``connect``.

    Call this FIRST in any session. USB-RS485 adapters show up with a USB VID:PID and
    usually a telling description/manufacturer (FTDI, CH340, CP210x...). If several
    adapters are present, connect to the most likely one and check whether motors are
    detected; it is cheap to connect to another port and look again. Relay the options
    to the user in plain English if it is ambiguous.
    """
    result = {"ports": _bus.list_ports(), "connected_port": _bus.connected_port}
    if _bus.simulated_notice:
        result["notice"] = _bus.simulated_notice
    return result


@mcp.tool()
def connect(port: str | None = None, detect: bool = True, detect_attempts: int = 3) -> dict:
    """Open a serial port (230400 baud) and auto-detect the motors on that RS-485 bus.

    ``port`` is a device name from ``list_serial_ports`` (e.g. "/dev/cu.usbserial-210",
    "COM3", "/dev/ttyUSB0"). If omitted: uses $GEAROTONS_SERIAL_PORT if set, else the
    single USB serial adapter if there is exactly one, else asks you to choose.

    Detection reboots every motor on the bus (positions re-zero at the current shaft
    location, MOSFETs turn off) and takes ~3 s per attempt. If no motors are found, the
    adapter may be the wrong one — try another port. Connecting to a different port
    replaces the previous connection, but only once the new port opens successfully —
    a failed attempt leaves the old connection intact.
    """
    result = _bus.connect(port=port, detect=detect, attempts=detect_attempts)
    if _bus.simulated_notice and isinstance(result, dict):
        result = {**result, "notice": _bus.simulated_notice}
    return result


@mcp.tool()
def disconnect() -> dict:
    """Close the serial port (e.g. to free it for another program, or before unplugging)."""
    return _bus.disconnect()


@mcp.tool()
def detect_devices(attempts: int = 3) -> dict:
    """Re-scan the connected bus for motors using the firmware's "Detect devices" command.

    Use after plugging in / powering on motors, or when a motor seems missing. Runs
    ``attempts`` merged detection rounds (more rounds = more reliable with many motors
    on one bus). CAUTION: this reboots every motor on the bus — positions re-zero at the
    current shaft location and MOSFETs turn off.
    """
    return {"motors": _bus.detect(attempts=attempts)}


@mcp.tool()
def list_motors() -> dict:
    """List the detected motors with live position, voltage, temperature, and status.

    Call after ``connect`` to see what is on the bus, or any time the user asks "what
    motors are connected / where are they". If this is empty but hardware is plugged in,
    run ``detect_devices`` or try another serial port.
    """
    return {"motors": _bus.list_motors(), "connected_port": _bus.connected_port}


# --------------------------------------------------------------------------------------
# High-level motion (preferred for ordinary "move it" requests)
# --------------------------------------------------------------------------------------

@mcp.tool()
def move_to(motor: str, degrees: float, speed_dps: float | None = None) -> dict:
    """Move one motor to an ABSOLUTE angle in degrees and wait for it to finish.

    Use when the user names a target position ("go to 90 degrees", "one full turn" =
    360). Angles are unbounded multi-turn (720 = two full turns). ``speed_dps`` is
    degrees/second (default 180). Enables the motor's MOSFETs automatically and returns
    the settled position. For very long moves (>30 s) prefer ``go_to_position`` plus
    ``get_n_queued_items`` polling so the tool call doesn't time out.

    motor: an alias number (e.g. 88) or a 16-hex-digit unique ID from list_motors.
    """
    return _bus.move_to(motor, degrees, speed_dps)


@mcp.tool()
def move_relative(motor: str, degrees: float, speed_dps: float | None = None) -> dict:
    """Move one motor by a RELATIVE amount in degrees (+/-) and wait for it to finish.

    Use for "turn a bit more", "back off 10 degrees", or incremental jogging. Any
    magnitude is allowed, including multiple full turns. ``speed_dps`` is degrees/second
    (default 180). Enables the MOSFETs automatically and returns the settled position.

    motor: an alias number (e.g. 88) or a 16-hex-digit unique ID from list_motors.
    """
    return _bus.move_relative(motor, degrees, speed_dps)


@mcp.tool()
def stop(motor: str | None = None) -> dict:
    """Immediately halt one motor, or ALL motors if ``motor`` is omitted.

    Use for "stop", "halt", or any sign something is wrong. Sends the firmware's
    emergency stop: motion halts and the move queue empties; holding torque remains.
    Use ``disable_mosfets`` afterwards to let the shaft spin freely.
    """
    return _bus.stop(motor)


@mcp.tool()
def get_motor_status(motor: str) -> dict:
    """One motor's live snapshot: position, supply voltage, temperature, decoded status.

    Call after moves to CONFIRM completion, or when the user asks "where is it / is it
    okay". Includes any fatal error decoded to plain English with suggested fixes
    (clear faults with ``system_reset``).
    """
    return _bus.motor_status(motor)


@mcp.tool()
def run_sequence(steps: list[dict]) -> dict:
    """Execute a choreographed sequence of steps, e.g. "draw a square" or "wave".

    Each step is one of:
        {"action": "move_to",       "motor": "88", "degrees": 90, "speed_dps": 120}
        {"action": "move_relative", "motor": "88", "degrees": -30}
        {"action": "stop"}                          # motor optional -> all
        {"action": "wait",          "seconds": 0.5}
        {"action": "command",       "motor": "88", "name": "vibrate", "params": [1]}

    Steps run in order; "command" runs any raw catalog command by tool name. Returns the
    final state of every detected motor.
    """
    run_sequence_steps(_bus, steps)
    return {"motors": _bus.list_motors()}


# --------------------------------------------------------------------------------------
# The full firmware command set, generated from the library's catalog
# --------------------------------------------------------------------------------------

# Provided natively above with the required reset/merge dance:
_SKIP_RAW_TOOLS = {"detect_devices"}

# Queued motion commands return as soon as the move is queued, not when it finishes.
_QUEUED_MOTION = {
    "trapezoid_move", "go_to_position", "move_with_velocity", "move_with_acceleration",
    "multimove",
}

_CAUTIONS = {
    "start_calibration": "The motor spins through a calibration routine; the shaft must "
                         "be free to rotate. Takes some seconds; the motor won't respond "
                         "until done.",
    "firmware_upgrade": "Flashes a firmware page (hex-encoded bytes). Wrong data can "
                        "brick the motor. Only use with a valid firmware file and the "
                        "user's explicit go-ahead.",
    "test_mode": "Developer/diagnostic modes; behavior depends on firmware internals.",
    "set_pid_constants": "Bad gains can make the motor oscillate violently.",
    "set_maximum_motor_current": "Higher current = more torque AND more heat; excessive "
                                 "settings can overheat the motor.",
    "set_device_alias": "Changes how the motor is addressed (takes effect immediately). "
                        "Re-run detect_devices afterwards.",
    "system_reset": "Reboots the motor (~2 s): position re-zeroes at the current shaft "
                    "location, MOSFETs disable, fatal errors clear.",
    "set_safety_limits": "Sets firmware position limits; moves beyond them fault the motor.",
    "crc32_control": "Changes protocol framing for ALL subsequent commands; only disable "
                     "CRC32 if you know why.",
    "homing": "The motor moves until it hits a physical obstruction, then zeroes there. "
              "Ensure a hard stop exists within maxDistance.",
    "zero_position": "Redefines the current shaft location as 0 degrees (no movement).",
    "trapezoid_move": "The displacement is RELATIVE to the current position.",
    "multimove": "moveList is a list of [value, duration_seconds] pairs (max 32): value "
                 "is degrees/s^2 for acceleration moves (moveTypes bit = 0) or degrees/s "
                 "for velocity moves (bit = 1); this server converts to firmware units. "
                 "The final move must bring the motor to a standstill or the firmware "
                 "raises a fatal error when the queue empties.",
}


def _tool_description(spec: CommandSpec) -> str:
    lines = [f"{spec.description} [Firmware command \"{spec.command_string}\", group: {spec.group}.]"]
    if spec.tool_name in _CAUTIONS:
        lines.append(f"NOTE: {_CAUTIONS[spec.tool_name]}")
    if spec.tool_name in _QUEUED_MOTION:
        lines.append(
            "This QUEUES the move and returns immediately; poll get_n_queued_items for "
            "completion, or use move_to/move_relative which wait. Requires "
            "enable_mosfets first."
        )
    if spec.params:
        lines.append("Parameters:")
        for p in spec.params:
            unit = f" (in {UNITS[p.unit_type]})" if p.unit_type else ""
            lines.append(f"  - {p.name}{unit}: {p.description}")
    if spec.outputs:
        lines.append("Returns:")
        for out in spec.outputs:
            lines.append(f"  - {out.name}: {out.description}")
    else:
        lines.append("Returns: success confirmation.")
    lines.append(MOTOR_ARG_DOC)
    return "\n".join(lines)


def _make_tool(spec: CommandSpec):
    """Build a typed function for one catalog command (FastMCP derives the schema)."""
    arg_defs = "".join(
        f", {p.name}: {p.py_type.__name__}" for p in spec.params
    )
    arg_names = ", ".join(p.name for p in spec.params)
    src = (
        f"def {spec.tool_name}(motor: str{arg_defs}) -> dict:\n"
        f"    return _execute(motor, {spec.tool_name!r}, [{arg_names}])\n"
    )
    namespace = {"_execute": _bus.execute}
    exec(src, namespace)  # noqa: S102 - source is generated from our own catalog
    return namespace[spec.tool_name]


def _register_catalog_tools() -> list[str]:
    registered = []
    for spec in load_catalog():
        if spec.tool_name in _SKIP_RAW_TOOLS:
            continue
        fn = _make_tool(spec)
        mcp.tool(name=spec.tool_name, description=_tool_description(spec))(fn)
        registered.append(spec.tool_name)
    return registered


CATALOG_TOOLS = _register_catalog_tools()


def main() -> None:
    """Entry point.

    Default transport is **stdio** — the local transport Claude Desktop / Claude Code /
    Cursor use to launch the server next to the motor. This is the normal, secure setup:
    the server runs on the same machine the motor is plugged into; nothing is exposed.

    To expose a motor *remotely* (e.g. behind a tunnel, for a demo), set
    ``GEAROTONS_MCP_TRANSPORT=http`` to serve a **Streamable-HTTP** endpoint at
    ``http://HOST:PORT/mcp``. Defaults bind to localhost (127.0.0.1) on purpose — put a
    tunnel/auth in front of it; never bind 0.0.0.0 straight to the internet without auth.
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
