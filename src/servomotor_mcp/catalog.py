"""Command catalog for the Gearotons M17 MCP server.

The ``servomotor`` library is fully data-driven: ``motor_commands.json`` defines every
command the firmware understands (name, inputs, outputs, units), and the library's ``M3``
class generates one Python method per entry. This module reads that same catalog and turns
it into ``CommandSpec`` objects the MCP server uses to generate one MCP tool per command —
so the server automatically tracks the library's full command set instead of hand-wrapping
a subset.

Catalog sources, in order of preference:

1. The JSON files inside the *installed* ``servomotor`` package (always matches the
   library that will actually execute the commands). Located via ``find_spec`` so nothing
   is imported at catalog-load time.
2. The snapshot bundled in ``servomotor_mcp/data/`` (lets the mock backend and the tool
   schemas work with no hardware library installed).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path

# The units every generated tool works in. These are fixed (and stated in each tool
# description) so the model never has to negotiate units; the library converts to the
# firmware's internal units (encoder counts / timesteps / mV / ...) per command.
UNITS: dict[str, str] = {
    "time": "seconds",
    "position": "degrees",
    "velocity": "degrees_per_second",
    "acceleration": "degrees_per_second_squared",
    "current": "milliamps",
    "voltage": "volts",
    "temperature": "celsius",
}


@dataclass(frozen=True)
class Param:
    name: str
    dtype: str          # library data type string, e.g. "i32", "buf10", "list_2d"
    description: str    # human text after the "dtype:" prefix
    unit_type: str | None  # "position" / "time" / ... when the value is unit-converted
    py_type: type       # annotation used for the generated tool signature


@dataclass(frozen=True)
class OutputField:
    name: str
    dtype: str
    description: str
    bits: tuple[str, ...] = ()  # per-bit meanings, when the JSON provides them


@dataclass(frozen=True)
class CommandSpec:
    command_string: str      # e.g. "Go to position" (exact library name)
    tool_name: str           # e.g. "go_to_position" (matches the M3 method name)
    enum: int
    description: str
    group: str
    params: tuple[Param, ...]
    outputs: tuple[OutputField, ...]  # empty for plain success responses
    multiple_responses: bool


def _data_dir() -> Path:
    """Directory holding motor_commands.json / data_types.json / error_codes.json."""
    spec = find_spec("servomotor")
    if spec is not None and spec.origin:
        lib_dir = Path(spec.origin).parent
        if (lib_dir / "motor_commands.json").exists():
            return lib_dir
    return Path(__file__).parent / "data"


def _load_json(name: str) -> object:
    return json.loads((_data_dir() / name).read_text(encoding="utf-8"))


def load_error_codes() -> dict[int, dict]:
    """Fatal error code -> {enum, short_desc, long_desc, causes, solutions}."""
    raw = _load_json("error_codes.json")
    return {e["code"]: e for e in raw.get("errors", [])}


def load_conversion_factors(motor_type: str = "M3") -> dict[str, float]:
    """unit name -> multiplier that converts a value in that unit to internal units."""
    return _load_json(f"unit_conversions_{motor_type}.json")["conversion_factors"]


def _integer_dtypes() -> set[str]:
    return {t["data_type"] for t in _load_json("data_types.json") if t.get("is_integer")}


def _split_description(text: str) -> tuple[str, str]:
    """The catalog encodes each field as 'dtype: human description'."""
    dtype, _, desc = text.partition(":")
    return dtype.strip(), desc.strip()


def _py_type(dtype: str, unit_type: str | None, int_types: set[str]) -> type:
    if unit_type is not None:
        return float  # user-facing value in degrees/seconds/etc.; library converts
    if dtype in int_types or dtype == "u8_alias":
        return int
    return str  # buffers, strings, 2D lists (python-literal string), hex pages


def _param_name(entry: dict, dtype: str, index: int) -> str:
    name = entry.get("ParameterName")
    if name:
        return name
    if dtype == "buf10":
        return "payload"
    return f"arg{index + 1}"


def load_catalog() -> list[CommandSpec]:
    int_types = _integer_dtypes()
    specs: list[CommandSpec] = []
    for cmd in _load_json("motor_commands.json"):
        params: list[Param] = []
        raw_inputs = cmd.get("Input") or []
        if isinstance(raw_inputs, dict):
            raw_inputs = [raw_inputs]
        for i, entry in enumerate(raw_inputs):
            dtype, desc = _split_description(entry["Description"])
            unit_type = (entry.get("UnitConversion") or {}).get("Type")
            if unit_type not in UNITS:
                # e.g. multimove's "mixed_acceleration_velocity_time" list — handled by
                # dedicated coercion in motors.py, not by scalar unit conversion.
                unit_type = None
            params.append(
                Param(
                    name=_param_name(entry, dtype, i),
                    dtype=dtype,
                    description=desc,
                    unit_type=unit_type,
                    py_type=_py_type(dtype, unit_type, int_types),
                )
            )

        outputs: list[OutputField] = []
        raw_outputs = cmd.get("Output")
        if isinstance(raw_outputs, list):
            for i, entry in enumerate(raw_outputs):
                dtype, desc = _split_description(entry["Description"])
                outputs.append(
                    OutputField(
                        name=entry.get("ParameterName") or f"value{i + 1}",
                        dtype=dtype,
                        description=desc,
                        bits=tuple(entry.get("Bit descriptions", ())),
                    )
                )

        specs.append(
            CommandSpec(
                command_string=cmd["CommandString"],
                tool_name=cmd["CommandString"].replace(" ", "_").lower(),
                enum=cmd["CommandEnum"],
                description=cmd.get("Description", ""),
                group=cmd.get("CommandGroup", ""),
                params=tuple(params),
                outputs=tuple(outputs),
                multiple_responses=bool(cmd.get("MultipleResponses", False)),
            )
        )
    return specs


def spec_by_tool_name() -> dict[str, CommandSpec]:
    return {s.tool_name: s for s in load_catalog()}
