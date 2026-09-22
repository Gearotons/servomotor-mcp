"""Motor bus backends for the Gearotons M17 MCP server.

Nothing is hardcoded about the setup: the server starts *disconnected*, enumerates the
system's serial ports on request, opens the one the model/user picks, and discovers the
motors on that bus with the firmware's "Detect devices" command. Every command in the
library's catalog is then executable against any discovered (or explicitly addressed)
motor.

Two backends share one interface:

- ``SerialBus`` — the real thing, wrapping the Gearotons ``servomotor`` library over a
  USB-RS485 adapter. Imported lazily so the package installs and the mock path runs
  without the hardware library.
- ``MockBus``  — an in-memory simulation (fake ports, fake motors, per-command canned
  behavior) used for development and CI.

Select with ``GEAROTONS_MOTOR_BACKEND=serial|mock|auto`` (default ``auto``: serial when
the ``servomotor`` library is installed, mock otherwise).

Cross-platform notes (macOS / Windows / Linux): port enumeration uses pyserial's
``list_ports`` (vendored inside ``servomotor``), which handles ``/dev/cu.*``, ``COM*``
and ``/dev/ttyUSB*`` alike. The library's own ``open_serial_port()`` helper is *not*
used on purpose — on failure it falls back to an interactive stdin menu (stdin is the
JSON-RPC channel for a stdio MCP server → deadlock) and it writes a cache file into the
package directory (not always writable). We open the port with the library's public
``create_serial_port`` factory instead and install it into ``communication`` directly.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from importlib.util import find_spec

from .catalog import (
    UNITS,
    CommandSpec,
    load_conversion_factors,
    load_error_codes,
    spec_by_tool_name,
)

BAUD_RATE = 230400
SERIAL_TIMEOUT_S = 1.2   # must cover the firmware's randomized detect-response delays
RESET_REBOOT_S = 1.5     # time a motor takes to reboot after "System reset"
DETECT_MIN_WINDOW_S = 1.1  # detect responses arrive over ~1s of randomized slots
BROADCAST = 255

_LOCK = threading.RLock()  # tools may run on worker threads; the bus is one wire


@contextlib.contextmanager
def _quiet_stdout():
    """Route library chatter off the JSON-RPC channel.

    The ``servomotor`` library prints diagnostics on stdout. Over a stdio transport,
    stdout IS the JSON-RPC stream, so any stray text corrupts it. Redirect to stderr
    (harmless, visible in client logs) around every library call.
    """
    with contextlib.redirect_stdout(sys.stderr):
        yield


class NotConnectedError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "Not connected to a serial port. Call list_serial_ports to see the options, "
            "then connect(port=...)."
        )


def _sanitize(value, dtype: str | None = None):
    """Make a decoded library response JSON-friendly and human-readable."""
    if isinstance(value, (bytes, bytearray)):
        text = value.rstrip(b"\x00 ").decode("utf-8", errors="replace")
        return {"hex": value.hex(), "text": text if text.isprintable() else None}
    if dtype == "u64_unique_id" and isinstance(value, int):
        return f"{value:016X}"
    if dtype in ("u24_version_number", "u32_version_number") and isinstance(value, list):
        return ".".join(str(b) for b in reversed(value))
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


class BusBase:
    """Shared logic: addressing, command execution plumbing, high-level motion helpers.

    Subclasses implement ``list_ports`` / ``connect`` / ``disconnect`` / ``_detect_once``
    and ``_raw_execute(address, tool_name, args)``.
    """

    #: Set on the simulator only: a sentence telling the model and user that no real motor will move.
    simulated_notice: str | None = None

    def __init__(self) -> None:
        self.connected_port: str | None = None
        self.devices: dict[int, int] = {}  # unique_id -> alias, from last detection
        self._enabled: set[int] = set()    # addresses with MOSFETs enabled by us
        self._specs: dict[str, CommandSpec] = spec_by_tool_name()
        self._errors = load_error_codes()
        self.default_speed_dps = float(os.environ.get("GEAROTONS_DEFAULT_SPEED_DPS", "180"))

    # -- addressing ---------------------------------------------------------------

    def resolve(self, motor: str | int) -> int:
        """Turn a tool's ``motor`` argument into a bus address.

        Accepts: an alias number 0-251 (int or decimal string), a 16-hex-digit unique ID
        (always unambiguous, works even with duplicate aliases), a single ASCII character
        alias (e.g. "X"), or "all"/"broadcast"/255 to address every motor at once.
        """
        if isinstance(motor, int):
            value = motor
        else:
            text = str(motor).strip()
            if text.lower() in ("all", "broadcast", "*"):
                return BROADCAST
            if len(text) == 16:
                try:
                    return int(text, 16)
                except ValueError:
                    pass
            try:
                value = int(text, 0)
            except ValueError:
                if len(text) == 1:
                    value = ord(text)
                else:
                    raise ValueError(
                        f"Cannot interpret motor address {motor!r}. Use an alias number "
                        "(e.g. 88), a 16-hex-digit unique ID, or 'all'."
                    ) from None
        if not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError(f"Motor address {value} out of range")
        return value

    def _spec(self, tool_name: str) -> CommandSpec:
        try:
            return self._specs[tool_name]
        except KeyError:
            raise ValueError(f"Unknown command: {tool_name!r}") from None

    # -- generic command execution --------------------------------------------------

    def execute(self, motor: str | int, tool_name: str, args: list) -> dict:
        """Run one catalog command against one motor and return a structured result."""
        spec = self._spec(tool_name)
        address = self.resolve(motor)
        if len(args) != len(spec.params):
            raise ValueError(
                f"{tool_name} takes {len(spec.params)} parameter(s) "
                f"({', '.join(p.name for p in spec.params)}), got {len(args)}"
            )
        coerced = [self._coerce_input(p, a) for p, a in zip(spec.params, args)]

        if tool_name == "multimove":
            coerced = self._prepare_multimove(coerced)

        with _LOCK:
            if tool_name == "system_reset":
                return self._do_system_reset(address)
            raw = self._raw_execute(address, tool_name, coerced)
            if tool_name == "enable_mosfets":
                self._enabled.add(address)
            elif tool_name in ("disable_mosfets", "emergency_stop"):
                self._enabled.discard(address)

        result = {
            "motor": self._motor_label(address),
            "command": spec.command_string,
            "response": self._shape_response(spec, address, raw),
        }
        if tool_name == "get_status":
            result["decoded"] = self._decode_status(raw)
        return result

    def _coerce_input(self, param, value):
        """Adapt friendly tool inputs to what the library layer expects."""
        if param.dtype == "buf10" and isinstance(value, str):
            data = value.encode("utf-8")[:10]
            return data.ljust(10, b"\x00")  # library requires exactly 10 bytes
        if param.dtype == "firmware_page" and isinstance(value, str):
            return bytes.fromhex(value)
        if param.dtype == "list_2d" and isinstance(value, (list, tuple)):
            return repr([list(item) for item in value])
        if param.py_type is float and isinstance(value, str):
            return float(value)
        if param.py_type is int and isinstance(value, str):
            return int(value, 0)
        return value

    def _prepare_multimove(self, args: list) -> list:
        """Convert multimove's mixed-unit move list to internal units.

        The tool takes ``moveList`` as [value, duration_seconds] pairs where ``value`` is
        degrees/s² for acceleration moves (moveTypes bit = 0) or degrees/s for velocity
        moves (bit = 1). The library's own M3.multimove conversion is broken in
        servomotor 0.10.0 (AttributeError on its mixed unit type), so the conversion —
        and the raw dispatch in SerialBus — happens here instead.
        """
        import ast  # noqa: PLC0415

        move_count, move_types, move_list = args
        if isinstance(move_list, str):
            move_list = ast.literal_eval(move_list)
        factors = load_conversion_factors()
        accel = factors[UNITS["acceleration"]]
        velocity = factors[UNITS["velocity"]]
        timesteps = factors[UNITS["time"]]
        converted = []
        for i, (value, duration_s) in enumerate(move_list):
            factor = velocity if (int(move_types) >> i) & 1 else accel
            converted.append([round(float(value) * factor), round(float(duration_s) * timesteps)])
        return [int(move_count), int(move_types), repr(converted)]

    def _shape_response(self, spec: CommandSpec, address: int, raw):
        """Name and sanitize the raw decoded values per the catalog's output spec."""
        if address == BROADCAST and raw in ([], None) and not spec.multiple_responses:
            return {"note": "broadcast command sent; no per-motor responses on broadcast"}
        if not spec.outputs:  # success_response commands return no payload fields
            return {"success": True}

        def name_one(values):
            if not isinstance(values, (list, tuple)):
                values = [values]
            return {
                out.name: _sanitize(v, out.dtype)
                for out, v in zip(spec.outputs, values)
            }

        if spec.multiple_responses:
            return [name_one(r) for r in (raw or [])]
        return name_one(raw)

    def _decode_status(self, raw) -> dict:
        """Turn get_status's [statusFlags, fatalErrorCode] into plain English."""
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        flags = int(values[0]) if values else 0
        fatal = int(values[1]) if len(values) > 1 else 0
        spec = self._spec("get_status")
        bit_docs = spec.outputs[0].bits if spec.outputs else ()
        active = []
        for bit, doc in enumerate(bit_docs):
            if flags & (1 << bit) and "Not used" not in doc:
                active.append(doc.partition(":")[2].strip() or doc)
        decoded: dict = {"status_flags": flags, "active_flags": active, "fatal_error_code": fatal}
        if fatal and fatal in self._errors:
            err = self._errors[fatal]
            decoded["fatal_error"] = {
                "enum": err.get("enum"),
                "description": err.get("long_desc") or err.get("short_desc"),
                "solutions": err.get("solutions", []),
            }
        elif fatal:
            decoded["fatal_error"] = {"enum": f"UNKNOWN_{fatal}"}
        return decoded

    def _do_system_reset(self, address: int) -> dict:
        # The reset interrupts the motor's own response mid-transmission, so a timeout /
        # partial read here is expected — swallow it, wait for the reboot, report cleanly.
        try:
            self._raw_execute(address, "system_reset", [])
        except Exception:
            pass
        self._enabled.clear() if address == BROADCAST else self._enabled.discard(address)
        time.sleep(RESET_REBOOT_S)
        return {
            "motor": self._motor_label(address),
            "command": "System reset",
            "response": {
                "success": True,
                "note": "motor rebooted; position re-zeroed at current shaft location, "
                        "MOSFETs disabled, any fatal error cleared",
            },
        }

    def _motor_label(self, address: int) -> str:
        if address == BROADCAST:
            return "all"
        if address > 255:
            return f"{address:016X}"
        return str(address)

    # -- detection --------------------------------------------------------------------

    def detect(self, attempts: int = 3) -> list[dict]:
        """Discover every motor on the bus with the firmware's "Detect devices" command.

        Follows the library's proven iterative pattern: broadcast a system reset, wait for
        the reboot, flush, then run a detect round; repeat ``attempts`` times and merge by
        unique ID (the firmware answers in randomized time slots, so one round can miss a
        device when several share the bus).

        Side effect (inherent to the protocol): every motor on the bus reboots — positions
        re-zero at the current shaft location and MOSFETs turn off.
        """
        self._require_connected()
        merged: dict[int, int] = {}
        with _LOCK:
            for _ in range(max(1, attempts)):
                try:
                    self._raw_execute(BROADCAST, "system_reset", [])
                except Exception:
                    pass
                time.sleep(RESET_REBOOT_S)
                self._flush()
                started = time.monotonic()
                try:
                    responses = self._detect_once() or []
                except Exception:
                    responses = []
                for item in responses:
                    uid, alias = int(item[0]), int(item[1])
                    merged[uid] = alias
                remaining = DETECT_MIN_WINDOW_S - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)
            self.devices = merged
            self._enabled.clear()
        return self.device_list()

    def device_list(self) -> list[dict]:
        return [
            {"alias": alias, "unique_id": f"{uid:016X}"}
            for uid, alias in sorted(self.devices.items(), key=lambda kv: kv[1])
        ]

    # -- high-level motion (what "rotate x to 30 degrees" should use) ------------------

    def _ensure_enabled(self, address: int) -> None:
        if address not in self._enabled:
            self._raw_execute(address, "enable_mosfets", [])
            self._enabled.add(address)

    def _duration_for(self, distance_deg: float, speed_dps: float | None) -> float:
        return max(abs(distance_deg) / (speed_dps or self.default_speed_dps), 0.15)

    def _wait_for_moves_done(self, address: int, expected_s: float) -> None:
        """Block until the motor's move queue drains (or a generous timeout passes)."""
        self._sleep(expected_s)
        deadline = time.monotonic() + max(expected_s, 1.0) + 5.0
        while time.monotonic() < deadline:
            try:
                queued = self._raw_execute(address, "get_n_queued_items", [])
            except Exception:
                break
            if not int(queued if not isinstance(queued, (list, tuple)) else queued[0]):
                break
            self._sleep(0.1)

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def move_to(self, motor: str | int, degrees: float, speed_dps: float | None = None) -> dict:
        address = self.resolve(motor)
        with _LOCK:
            self._ensure_enabled(address)
            current = float(self._raw_execute(address, "get_position", []))
            duration = self._duration_for(degrees - current, speed_dps)
            self._raw_execute(address, "go_to_position", [degrees, duration])
            self._wait_for_moves_done(address, duration)
            return self.motor_status(address)

    def move_relative(self, motor: str | int, degrees: float, speed_dps: float | None = None) -> dict:
        address = self.resolve(motor)
        with _LOCK:
            self._ensure_enabled(address)
            duration = self._duration_for(degrees, speed_dps)
            self._raw_execute(address, "trapezoid_move", [degrees, duration])
            self._wait_for_moves_done(address, duration)
            return self.motor_status(address)

    def stop(self, motor: str | int | None = None) -> dict:
        """Emergency-stop: the firmware disables the driver outputs and empties the move queue.

        No holding torque afterwards; send ``enable_mosfets`` before the next move.
        """
        address = BROADCAST if motor is None else self.resolve(motor)
        with _LOCK:
            self._raw_execute(address, "emergency_stop", [])
        return {"stopped": self._motor_label(address)}

    def motor_status(self, motor: str | int) -> dict:
        """One motor's live snapshot: position, voltage, temperature, decoded status."""
        address = self.resolve(motor)
        with _LOCK:
            snapshot: dict = {"motor": self._motor_label(address)}
            alias = self._alias_for(address)
            if alias is not None:
                snapshot["alias"] = alias
            uid = self._uid_for(address)
            if uid is not None:
                snapshot["unique_id"] = f"{uid:016X}"
            snapshot["position_deg"] = round(float(self._raw_execute(address, "get_position", [])), 3)
            try:
                snapshot["voltage_v"] = float(self._raw_execute(address, "get_supply_voltage", []))
                snapshot["temperature_c"] = float(self._raw_execute(address, "get_temperature", []))
            except Exception:
                pass
            try:
                status = self._raw_execute(address, "get_status", [])
                snapshot["status"] = self._decode_status(status)
            except Exception:
                pass
        return snapshot

    def list_motors(self) -> list[dict]:
        self._require_connected()
        out = []
        for uid, alias in sorted(self.devices.items(), key=lambda kv: kv[1]):
            try:
                out.append(self.motor_status(uid))
            except Exception as exc:
                out.append({"alias": alias, "unique_id": f"{uid:016X}", "error": str(exc)})
        return out

    def _alias_for(self, address: int) -> int | None:
        if address > 255:
            return self.devices.get(address)
        return address if address != BROADCAST else None

    def _uid_for(self, address: int) -> int | None:
        if address > 255:
            return address
        for uid, alias in self.devices.items():
            if alias == address:
                return uid
        return None

    # -- to be provided by subclasses --------------------------------------------------

    def list_ports(self) -> list[dict]:
        raise NotImplementedError

    def connect(self, port: str | None = None, detect: bool = True, attempts: int = 3) -> dict:
        raise NotImplementedError

    def disconnect(self) -> dict:
        raise NotImplementedError

    def _require_connected(self) -> None:
        if self.connected_port is None:
            raise NotConnectedError

    def _flush(self) -> None:
        raise NotImplementedError

    def _detect_once(self) -> list:
        raise NotImplementedError

    def _raw_execute(self, address: int, tool_name: str, args: list):
        raise NotImplementedError

    def _pick_port(self, port: str | None, ports: list[dict]) -> str:
        """Resolve the port to open when the caller gave none or gave a fuzzy name."""
        if port:
            for p in ports:
                if port in (p["device"], p.get("name")):
                    return p["device"]
            return port  # not in the enumeration (e.g. symlink) — let open() decide
        env_port = os.environ.get("GEAROTONS_SERIAL_PORT")
        if env_port:
            return env_port
        usb = [p for p in ports if p.get("vid_pid")]
        if len(usb) == 1:
            return usb[0]["device"]
        if len(ports) == 1:
            return ports[0]["device"]
        raise ValueError(
            "No port specified and more than one candidate exists. Call list_serial_ports "
            f"and pick one of: {[p['device'] for p in ports]}"
        )


class SerialBus(BusBase):
    """Real backend over the Gearotons ``servomotor`` library and a USB-RS485 adapter."""

    def __init__(self) -> None:
        super().__init__()
        self._sm = None          # servomotor module, imported at connect time
        self._handles: dict[int, object] = {}  # address -> configured M3 instance

    def _library(self):
        if self._sm is None:
            try:
                with _quiet_stdout():
                    import servomotor  # noqa: PLC0415 - deliberate lazy import
            except ImportError as exc:
                raise RuntimeError(
                    "The 'servomotor' library is not installed. Install the serial extra: "
                    "pip install 'servomotor-mcp[serial]'"
                ) from exc
            self._sm = servomotor
        return self._sm

    def list_ports(self) -> list[dict]:
        # Prefer the pyserial vendored inside servomotor (always present with [serial]);
        # fall back to a standalone pyserial if the user happens to have one.
        try:
            from servomotor.vendor.serial.tools import list_ports  # noqa: PLC0415
        except ImportError:
            try:
                from serial.tools import list_ports  # noqa: PLC0415
            except ImportError as exc:
                raise RuntimeError(
                    "Serial port enumeration needs the 'servomotor' library (or pyserial). "
                    "Install with: pip install 'servomotor-mcp[serial]'"
                ) from exc
        out = []
        for p in sorted(list_ports.comports(), key=lambda p: p.device):
            vid_pid = f"{p.vid:04X}:{p.pid:04X}" if p.vid is not None else None
            out.append(
                {
                    "device": p.device,
                    "description": p.description if p.description != "n/a" else None,
                    "manufacturer": getattr(p, "manufacturer", None),
                    "serial_number": getattr(p, "serial_number", None),
                    "vid_pid": vid_pid,
                    "likely_usb_serial_adapter": vid_pid is not None,
                    "connected": p.device == self.connected_port,
                }
            )
        return out

    def connect(self, port: str | None = None, detect: bool = True, attempts: int = 3) -> dict:
        sm = self._library()
        from servomotor import communication  # noqa: PLC0415
        from servomotor.serial_abstraction import create_serial_port  # noqa: PLC0415

        with _LOCK:
            ports = self.list_ports()
            device = self._pick_port(port, ports)
            if device == self.connected_port:
                self.disconnect()  # same port: must release it before reopening
            try:
                with _quiet_stdout():
                    ser = create_serial_port(device, BAUD_RATE, timeout=SERIAL_TIMEOUT_S)
            except Exception as exc:
                available = [p["device"] for p in ports]
                raise RuntimeError(
                    f"Could not open serial port {device!r}: {exc}. "
                    f"Available ports: {available}"
                    + (f". Still connected to {self.connected_port!r}."
                       if self.connected_port else "")
                ) from exc
            if self.connected_port is not None:
                self.disconnect()  # a different port opened fine; now drop the old one
            communication.serial_port = device
            communication.ser = ser
            self.connected_port = device
            self._handles.clear()
            self._enabled.clear()
            self.devices = {}

        result: dict = {"connected_port": device, "baud_rate": BAUD_RATE}
        if detect:
            result["motors"] = self.detect(attempts=attempts)
            if not result["motors"]:
                result["note"] = (
                    "No motors responded on this bus. Check power and wiring, or try "
                    "another port from list_serial_ports."
                )
        return result

    def disconnect(self) -> dict:
        from servomotor import communication  # noqa: PLC0415

        with _LOCK:
            port = self.connected_port
            if communication.ser is not None:
                try:
                    communication.ser.close()
                except Exception:
                    pass
                communication.ser = None
            self.connected_port = None
            self._handles.clear()
            self._enabled.clear()
            self.devices = {}
        return {"disconnected": port}

    def _handle(self, address: int):
        if address not in self._handles:
            sm = self._library()
            with _quiet_stdout():
                self._handles[address] = sm.M3(
                    alias_or_unique_id=address,
                    time_unit=UNITS["time"],
                    position_unit=UNITS["position"],
                    velocity_unit=UNITS["velocity"],
                    acceleration_unit=UNITS["acceleration"],
                    current_unit=UNITS["current"],
                    voltage_unit=UNITS["voltage"],
                    temperature_unit=UNITS["temperature"],
                    verbose=0,
                )
        return self._handles[address]

    def _flush(self) -> None:
        with _quiet_stdout():
            self._library().flush_receive_buffer()

    def _detect_once(self) -> list:
        with _quiet_stdout():
            return self._handle(BROADCAST).detect_devices()

    def _raw_execute(self, address: int, tool_name: str, args: list):
        self._require_connected()
        if tool_name == "multimove":
            # Bypass M3.multimove (broken unit conversion in servomotor 0.10.0); the
            # arguments were already converted to internal units by _prepare_multimove.
            from servomotor import communication  # noqa: PLC0415

            try:
                with _quiet_stdout():
                    return communication.execute_command(
                        self._spec(tool_name).enum, args,
                        alias_or_unique_id=address, verbose=0,
                    )
            except SystemExit as exc:
                raise RuntimeError(
                    "servomotor command 'multimove' failed (library error). Check the "
                    "move list against the queue size (max 32 moves)."
                ) from exc
        method = getattr(self._handle(address), tool_name, None)
        if method is None:
            raise ValueError(f"The installed servomotor library has no command {tool_name!r}")
        from servomotor import communication  # noqa: PLC0415

        try:
            with _quiet_stdout():
                return method(*args)
        except communication.TimeoutError as exc:
            raise RuntimeError(
                f"No response from motor {self._motor_label(address)} "
                f"({self._spec(tool_name).command_string}). Is it powered, wired to "
                f"{self.connected_port!r}, and at this address? detect_devices lists "
                "what is actually on the bus."
            ) from exc
        except SystemExit as exc:
            # The library exits the process on command errors; keep the server alive.
            raise RuntimeError(
                f"servomotor command {tool_name!r} failed (library error). Check the "
                "arguments, and use get_status to look for a fatal error state."
            ) from exc


class MockBus(BusBase):
    """In-memory simulation: two fake ports, two motors on the first, none on the second."""

    PORTS = (
        {"device": "MOCK0", "description": "Simulated USB-RS485 adapter (2 motors)",
         "manufacturer": "Gearotons (simulated)", "serial_number": "SIM0",
         "vid_pid": "1A86:7523", "likely_usb_serial_adapter": True},
        {"device": "MOCK1", "description": "Simulated USB-RS485 adapter (no motors)",
         "manufacturer": "Gearotons (simulated)", "serial_number": "SIM1",
         "vid_pid": "1A86:7523", "likely_usb_serial_adapter": True},
    )
    MOTORS_ON_MOCK0 = {0x0123456789ABCDEF: 42, 0xFEDCBA9876543210: 43}

    def __init__(self) -> None:
        super().__init__()
        self._positions: dict[int, float] = {}
        self._mock_enabled: dict[int, bool] = {}
        self.log: list[str] = []

    def list_ports(self) -> list[dict]:
        return [dict(p, connected=(p["device"] == self.connected_port)) for p in self.PORTS]

    def connect(self, port: str | None = None, detect: bool = True, attempts: int = 3) -> dict:
        with _LOCK:
            device = self._pick_port(port, self.list_ports())
            if device not in [p["device"] for p in self.PORTS]:
                raise RuntimeError(
                    f"Could not open serial port {device!r}: simulated port not found. "
                    f"Available ports: {[p['device'] for p in self.PORTS]}"
                )
            self.connected_port = device
            self.devices = {}
            self._enabled.clear()
        result: dict = {"connected_port": device, "baud_rate": BAUD_RATE}
        if detect:
            result["motors"] = self.detect(attempts=attempts)
            if not result["motors"]:
                result["note"] = (
                    "No motors responded on this bus. Check power and wiring, or try "
                    "another port from list_serial_ports."
                )
        return result

    def disconnect(self) -> dict:
        port = self.connected_port
        self.connected_port = None
        self.devices = {}
        self._enabled.clear()
        return {"disconnected": port}

    def _sleep(self, seconds: float) -> None:
        pass  # simulated moves are instantaneous

    def detect(self, attempts: int = 3) -> list[dict]:
        self._require_connected()
        self.log.append(f"detect attempts={attempts}")
        self.devices = (
            dict(self.MOTORS_ON_MOCK0) if self.connected_port == "MOCK0" else {}
        )
        for uid in self.devices:
            self._positions[uid] = 0.0  # detection reboots every motor, like the real bus
            self._mock_enabled[uid] = False
        self._enabled.clear()
        return self.device_list()

    def _bus_addresses(self) -> set[int]:
        addrs: set[int] = set()
        for uid, alias in self.devices.items():
            addrs.add(uid)
            addrs.add(alias)
        return addrs

    def _canonical(self, address: int) -> int:
        """Fold alias/uid addressing of the same simulated motor onto its uid."""
        if address in self.devices:
            return address
        for uid, alias in self.devices.items():
            if alias == address:
                return uid
        raise RuntimeError(
            f"No simulated motor at address {self._motor_label(address)} "
            f"(bus has: {self.device_list()})"
        )

    def _flush(self) -> None:
        pass

    def _detect_once(self) -> list:
        motors = self.MOTORS_ON_MOCK0 if self.connected_port == "MOCK0" else {}
        return [[uid, alias] for uid, alias in motors.items()]

    def _raw_execute(self, address: int, tool_name: str, args: list):
        self._require_connected()
        self.log.append(f"{self._motor_label(address)} {tool_name} {args}")
        if address == BROADCAST:
            for uid in list(self.devices):
                self._simulate(uid, tool_name, args)
            return []  # like the real bus: broadcast produces no responses
        return self._simulate(self._canonical(address), tool_name, args)

    def _simulate(self, uid: int, tool_name: str, args: list):
        pos = self._positions.setdefault(uid, 0.0)
        if tool_name == "enable_mosfets":
            self._mock_enabled[uid] = True
            return b""
        if tool_name == "disable_mosfets" or tool_name == "emergency_stop":
            self._mock_enabled[uid] = False
            return b""
        if tool_name == "system_reset":
            self._positions[uid] = 0.0
            self._mock_enabled[uid] = False
            return b""
        if tool_name == "zero_position":
            self._positions[uid] = 0.0
            return b""
        if tool_name == "go_to_position":
            self._positions[uid] = float(args[0])
            return b""
        if tool_name == "trapezoid_move":
            self._positions[uid] = pos + float(args[0])
            return b""
        if tool_name == "get_position":
            return self._positions[uid]
        if tool_name == "get_n_queued_items":
            return 0
        if tool_name == "get_status":
            return [0b10 if self._mock_enabled[uid] else 0, 0]
        if tool_name == "get_supply_voltage":
            return 24.0
        if tool_name == "get_temperature":
            return 25
        if tool_name == "ping":
            return bytes(args[0]) if args else b"\x00" * 10
        if tool_name == "get_firmware_version":
            return [[0, 0, 15, 0], 0]
        if tool_name == "get_product_description":
            return "Simulated Gearotons M17"
        if tool_name == "get_comprehensive_position":
            return [self._positions[uid], self._positions[uid], 0]
        spec = self._spec(tool_name)
        if not spec.outputs:
            return b""
        return [0] * len(spec.outputs)


SIMULATED_NOTICE_NO_LIBRARY = (
    "SIMULATED MOTORS: the 'servomotor' library is not installed, so this server is running its "
    "built-in simulator and no real motor will move. To drive real M17 motors, install "
    "'servomotor-mcp[serial]' (for uvx: uvx --from 'servomotor-mcp[serial]' servomotor-mcp) and "
    "restart the server. Set GEAROTONS_MOTOR_BACKEND=mock to use the simulator on purpose."
)
SIMULATED_NOTICE_REQUESTED = (
    "SIMULATED MOTORS: GEAROTONS_MOTOR_BACKEND=mock is set, so these are simulated ports and motors; "
    "no real motor will move."
)


def get_bus() -> BusBase:
    """Construct the backend selected by ``GEAROTONS_MOTOR_BACKEND`` (default: auto).

    ``auto`` uses the real serial backend when the ``servomotor`` library is installed and the
    simulator otherwise. Whenever the simulator is used, the returned bus carries a
    ``simulated_notice`` (surfaced to the model by ``list_serial_ports`` and ``connect``) and a
    warning is written to stderr, so a user with real hardware never ends up on the simulator
    without being told.
    """
    backend = os.environ.get("GEAROTONS_MOTOR_BACKEND", "auto").lower()
    notice = SIMULATED_NOTICE_REQUESTED
    if backend == "auto":
        if find_spec("servomotor"):
            backend = "serial"
        else:
            backend = "mock"
            notice = SIMULATED_NOTICE_NO_LIBRARY
    if backend == "serial":
        return SerialBus()
    bus = MockBus()
    bus.simulated_notice = notice
    print(f"servomotor-mcp: {notice}", file=sys.stderr, flush=True)
    return bus
