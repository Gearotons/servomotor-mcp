"""Motor backends for the Gearotons M17 MCP server.

Two backends share one interface so the MCP server and tools can be built and tested
with no hardware, then point at real motors by flipping one env var:

- ``MockBus``  — an in-memory simulation. Moves complete instantly (or after a short
  simulated delay) and are logged. Used for development, CI, and the scripted demo dry-run.
- ``SerialBus`` — wraps the real Gearotons ``servomotor`` Python library over a
  USB↔RS-485 adapter. Imported lazily so the package installs and the mock path runs
  without the hardware library present.

Select with ``GEAROTONS_MOTOR_BACKEND=mock|serial`` (default: ``mock``).
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Protocol


@contextlib.contextmanager
def _quiet_stdout():
    """Route library chatter off the JSON-RPC channel.

    The Gearotons ``servomotor`` library prints connection/diagnostic messages (and can
    drop into an interactive port-selection menu) on **stdout**. When this MCP server runs
    over stdio, stdout IS the JSON-RPC transport, so any stray text corrupts the stream and
    the client reports "not valid JSON". Redirect the library's stdout to stderr (which the
    client shows in logs, harmlessly) for the duration of every library call.
    """
    with contextlib.redirect_stdout(sys.stderr):
        yield


@dataclass
class MotorState:
    """A snapshot of one motor's state, returned by status calls."""

    alias: str
    position_deg: float
    moving: bool
    voltage_v: float | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "alias": self.alias,
            "position_deg": round(self.position_deg, 3),
            "moving": self.moving,
            "voltage_v": self.voltage_v,
            "error": self.error,
        }


class MotorBus(Protocol):
    """The interface every backend implements. Angles are degrees; speed is deg/s."""

    def list_motors(self) -> list[MotorState]: ...
    def move_to(self, alias: str, degrees: float, speed: float | None = None) -> MotorState: ...
    def move_relative(self, alias: str, degrees: float, speed: float | None = None) -> MotorState: ...
    def trapezoid_move(self, alias: str, degrees: float, duration_s: float) -> MotorState: ...
    def home(self, alias: str | None = None) -> list[MotorState]: ...
    def get_status(self, alias: str | None = None) -> list[MotorState]: ...
    def stop(self, alias: str | None = None) -> list[MotorState]: ...
    def reset(self, alias: str | None = None) -> list[MotorState]: ...


@dataclass
class _SimMotor:
    alias: str
    position_deg: float = 0.0
    voltage_v: float = 24.0


@dataclass
class MockBus:
    """In-memory simulation of an RS-485 daisy-chain of M17 motors.

    Moves are applied instantly to the model; ``simulate_seconds`` adds a small,
    proportional delay so a scripted demo looks lifelike without real hardware.
    Every action is appended to ``log`` for inspection in tests and the demo dry-run.
    """

    aliases: tuple[str, ...] = ("x", "y", "z")
    simulate_seconds: float = 0.0
    _motors: dict[str, _SimMotor] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self._motors:
            self._motors = {a: _SimMotor(alias=a) for a in self.aliases}

    def _require(self, alias: str) -> _SimMotor:
        if alias not in self._motors:
            raise KeyError(f"unknown motor alias: {alias!r} (known: {sorted(self._motors)})")
        return self._motors[alias]

    def _settle(self, distance_deg: float, speed: float | None) -> None:
        if self.simulate_seconds <= 0:
            return
        # Cheap, bounded delay so the demo reads as real motion.
        time.sleep(min(self.simulate_seconds, abs(distance_deg) / (speed or 360.0)))

    def _snapshot(self, m: _SimMotor, moving: bool = False) -> MotorState:
        return MotorState(alias=m.alias, position_deg=m.position_deg, moving=moving, voltage_v=m.voltage_v)

    def list_motors(self) -> list[MotorState]:
        self.log.append("list_motors")
        return [self._snapshot(m) for m in self._motors.values()]

    def move_to(self, alias: str, degrees: float, speed: float | None = None) -> MotorState:
        m = self._require(alias)
        self._settle(degrees - m.position_deg, speed)
        m.position_deg = degrees
        self.log.append(f"move_to {alias} -> {degrees} (speed={speed})")
        return self._snapshot(m)

    def move_relative(self, alias: str, degrees: float, speed: float | None = None) -> MotorState:
        m = self._require(alias)
        self._settle(degrees, speed)
        m.position_deg += degrees
        self.log.append(f"move_relative {alias} += {degrees} (speed={speed})")
        return self._snapshot(m)

    def trapezoid_move(self, alias: str, degrees: float, duration_s: float) -> MotorState:
        m = self._require(alias)
        if self.simulate_seconds > 0:
            time.sleep(min(self.simulate_seconds, duration_s))
        m.position_deg = degrees
        self.log.append(f"trapezoid_move {alias} -> {degrees} over {duration_s}s")
        return self._snapshot(m)

    def home(self, alias: str | None = None) -> list[MotorState]:
        targets = [alias] if alias else list(self._motors)
        for a in targets:
            self._require(a).position_deg = 0.0
        self.log.append(f"home {alias or 'all'}")
        return [self._snapshot(self._motors[a]) for a in targets]

    def get_status(self, alias: str | None = None) -> list[MotorState]:
        targets = [alias] if alias else list(self._motors)
        return [self._snapshot(self._require(a)) for a in targets]

    def stop(self, alias: str | None = None) -> list[MotorState]:
        self.log.append(f"stop {alias or 'all'}")
        return self.get_status(alias)

    def reset(self, alias: str | None = None) -> list[MotorState]:
        # Simulated motors don't fault; clears the (simulated) error and recenters nothing.
        targets = [alias] if alias else list(self._motors)
        self.log.append(f"reset {alias or 'all'}")
        return [self._snapshot(self._motors[a]) for a in targets]


class SerialBus:
    """Real backend: wraps the Gearotons ``servomotor`` Python library over RS-485.

    Verified against a physical M17 (fw 0.15.0.0) on 2026-06-08 — see
    ``hardware_tests/`` and ``logs/hardware-2026-06-08.md``.

    Friendly aliases (``x``/``y``/``z`` used by the MCP tools) are mapped to real device
    addresses (the motor's 1-byte alias, e.g. 88) either explicitly via
    ``GEAROTONS_SERIAL_MOTORS`` (JSON: ``{"x": 88}``) or by auto-detecting the bus and
    naming each device ``m{alias}``. Library quirks handled here so the MCP server stays up:

    - The library prints + ``sys.exit()``s (SystemExit) on a command error — wrapped and
      re-raised as ``RuntimeError`` so one bad call can't kill the server.
    - ``trapezoid_move`` is a RELATIVE displacement, so absolute ``move_to`` reads the
      current position and moves the delta.
    - Moves block for their duration (the call returns after the motion completes), so the
      reported state is the settled position.
    """

    def __init__(
        self,
        port: str,
        motor_map: dict[str, int] | None = None,
        default_speed_dps: float = 180.0,
        baud: int = 230400,
    ) -> None:
        try:
            import servomotor
            from servomotor import communication
            from servomotor.device_detection import detect_devices_iteratively
        except ImportError as exc:  # pragma: no cover - hardware path
            raise RuntimeError(
                "GEAROTONS_MOTOR_BACKEND=serial requires the 'servomotor' library and a "
                "USB-RS485 adapter. Install it ('pip install servomotor' or add the repo's "
                "python_programs to PYTHONPATH), or use the mock backend."
            ) from exc
        self._sm = servomotor
        self.port = port
        self.baud = baud
        self.default_speed_dps = default_speed_dps
        self._enabled: set[str] = set()

        # Set the port explicitly via the module global so the library never falls back to a
        # cached device file or the interactive stdin menu — either of which hangs/corrupts a
        # stdio MCP server. ``open_serial_port()`` reads this global and takes NO port argument
        # (its only positional is ``timeout``), so it must be called with no args. All of this
        # prints to stdout, so keep it off the JSON-RPC channel.
        communication.serial_port = port
        with _quiet_stdout():
            servomotor.open_serial_port()

            if motor_map is None:
                # Auto-detect: a broadcast M3 + iterative detection, then name each m{alias}.
                servomotor.M3(alias_or_unique_id=255, verbose=0)
                devices = detect_devices_iteratively(3, verbose=False) or []
                motor_map = {f"m{d.alias}": d.alias for d in devices}
            self.motor_map = motor_map

            # One M3 handle per friendly alias, in degrees/seconds.
            self._m = {
                name: servomotor.M3(
                    alias_or_unique_id=addr, time_unit="seconds",
                    position_unit="degrees", verbose=0
                )
                for name, addr in motor_map.items()
            }

    # --- library-error guard ----------------------------------------------------------

    @staticmethod
    def _safe(fn, *args):
        """Call a library method; convert its SystemExit-on-error into RuntimeError.

        Wrapped in ``_quiet_stdout`` because the library may print (e.g. error/troubleshooting
        text) mid-command, which would otherwise corrupt the stdio JSON-RPC stream.
        """
        try:
            with _quiet_stdout():
                return fn(*args)
        except SystemExit as exc:  # library exits the process on a command error
            raise RuntimeError(f"servomotor command failed ({fn.__name__})") from exc

    def _require(self, alias: str):
        if alias not in self._m:
            raise KeyError(f"unknown motor alias: {alias!r} (known: {sorted(self._m)})")
        return self._m[alias]

    def _ensure_enabled(self, alias: str) -> None:
        if alias not in self._enabled:
            self._safe(self._require(alias).enable_mosfets)
            self._enabled.add(alias)

    def _duration_for(self, distance_deg: float, speed: float | None) -> float:
        spd = speed or self.default_speed_dps
        return max(abs(distance_deg) / spd, 0.15)

    def _state(self, alias: str, moving: bool = False) -> MotorState:
        m = self._require(alias)
        pos = float(self._safe(m.get_position))
        volts = None
        err = None
        try:
            volts = float(self._safe(m.get_supply_voltage)) / 1000.0
            status = self._safe(m.get_status)
            # status is [status_flags, fatal_error_code]; non-zero fatal => report it
            if isinstance(status, (list, tuple)) and len(status) >= 2 and status[1]:
                err = f"fatal_error_code={status[1]}"
        except Exception:
            pass
        return MotorState(alias=alias, position_deg=pos, moving=moving, voltage_v=volts, error=err)

    # --- MotorBus interface -----------------------------------------------------------

    def list_motors(self) -> list[MotorState]:
        return [self._state(name) for name in self._m]

    def move_to(self, alias: str, degrees: float, speed: float | None = None) -> MotorState:
        m = self._require(alias)
        self._ensure_enabled(alias)
        # Native ABSOLUTE move (go_to_position) — atomic, no read-then-relative race.
        # Current position is read only to derive a duration from the requested speed.
        current = float(self._safe(m.get_position))
        dur = self._duration_for(degrees - current, speed)
        self._safe(m.go_to_position, degrees, dur)
        time.sleep(dur * 1.15)
        return self._state(alias)

    def move_relative(self, alias: str, degrees: float, speed: float | None = None) -> MotorState:
        m = self._require(alias)
        self._ensure_enabled(alias)
        dur = self._duration_for(degrees, speed)
        self._safe(m.trapezoid_move, degrees, dur)
        time.sleep(dur * 1.15)
        return self._state(alias)

    def trapezoid_move(self, alias: str, degrees: float, duration_s: float) -> MotorState:
        m = self._require(alias)
        self._ensure_enabled(alias)
        # `degrees` is an absolute target (matches MockBus semantics). go_to_position runs a
        # smooth profile to the target over the given duration.
        self._safe(m.go_to_position, degrees, duration_s)
        time.sleep(duration_s * 1.15)
        return self._state(alias)

    def home(self, alias: str | None = None) -> list[MotorState]:
        targets = [alias] if alias else list(self._m)
        out = []
        for a in targets:
            out.append(self.move_to(a, 0.0))  # move to absolute zero
        return out

    def get_status(self, alias: str | None = None) -> list[MotorState]:
        targets = [alias] if alias else list(self._m)
        return [self._state(a) for a in targets]

    def stop(self, alias: str | None = None) -> list[MotorState]:
        targets = [alias] if alias else list(self._m)
        for a in targets:
            self._safe(self._require(a).disable_mosfets)
            self._enabled.discard(a)
        return [self._state(a) for a in targets]

    def reset(self, alias: str | None = None) -> list[MotorState]:
        """Recover a motor from a latched fatal error via the firmware's system reset.

        The motor reboots (~2 s) and returns to a clean state. Use after a fault shows up in
        ``get_status``/``error`` (e.g. ``ERROR_RUN_OUT_OF_QUEUE_ITEMS`` from an unsupported
        velocity move) so the server never gets wedged. ``system_reset`` interrupts its own
        response, so the call is expected to raise mid-reset — that's swallowed here.
        """
        targets = [alias] if alias else list(self._m)
        for a in targets:
            try:
                self._require(a).system_reset()
            except BaseException:  # noqa: BLE001 - reset interrupts its own response
                pass
            self._enabled.discard(a)
        time.sleep(2.0)  # allow the motor(s) to reboot before reading state
        return [self._state(a) for a in targets]

    def close(self) -> None:
        try:
            self.stop()
        finally:
            self._sm.close_serial_port()


def get_bus() -> MotorBus:
    """Construct the backend selected by ``GEAROTONS_MOTOR_BACKEND`` (default: mock)."""
    backend = os.environ.get("GEAROTONS_MOTOR_BACKEND", "mock").lower()
    aliases = tuple(
        a.strip() for a in os.environ.get("GEAROTONS_MOTOR_ALIASES", "x,y,z").split(",") if a.strip()
    )
    if backend == "serial":
        import json

        port = os.environ.get("GEAROTONS_SERIAL_PORT", "/dev/cu.usbserial-210")
        raw = os.environ.get("GEAROTONS_SERIAL_MOTORS", "").strip()
        motor_map = {k: int(v) for k, v in json.loads(raw).items()} if raw else None
        return SerialBus(port=port, motor_map=motor_map)
    sim = float(os.environ.get("GEAROTONS_MOCK_SIM_SECONDS", "0"))
    return MockBus(aliases=aliases, simulate_seconds=sim)
