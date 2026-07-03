"""The command catalog must cover the library's full command set with usable specs."""

from servomotor_mcp.catalog import UNITS, load_catalog, load_error_codes, spec_by_tool_name


def test_full_command_set_loaded():
    specs = load_catalog()
    assert len(specs) >= 48  # library 0.10.0 ships 48; more is fine, fewer is a regression
    names = {s.tool_name for s in specs}
    # Spot-check the spread: basic control, motion, queries, configuration, protocol.
    for expected in (
        "enable_mosfets", "disable_mosfets", "trapezoid_move", "go_to_position",
        "detect_devices", "get_status", "get_position", "get_supply_voltage",
        "get_temperature", "system_reset", "emergency_stop", "multimove", "ping",
        "set_device_alias", "firmware_upgrade", "get_communication_statistics",
    ):
        assert expected in names, expected


def test_tool_names_are_valid_python_identifiers():
    for spec in load_catalog():
        assert spec.tool_name.isidentifier()
        for p in spec.params:
            assert p.name.isidentifier(), (spec.tool_name, p.name)


def test_param_types_and_units():
    by_name = spec_by_tool_name()
    go = by_name["go_to_position"]
    assert [p.name for p in go.params] == ["position", "duration"]
    assert all(p.py_type is float for p in go.params)  # unit-converted -> float
    assert go.params[0].unit_type == "position"
    assert UNITS[go.params[0].unit_type] == "degrees"

    ping = by_name["ping"]
    assert len(ping.params) == 1
    assert ping.params[0].py_type is str  # buf10 payload

    multimove = by_name["multimove"]
    dtypes = {p.name: p.dtype for p in multimove.params}
    assert dtypes["moveList"] == "list_2d"


def test_get_status_outputs_carry_bit_docs():
    spec = spec_by_tool_name()["get_status"]
    assert spec.outputs[0].name == "statusFlags"
    assert any("MOSFETs are enabled" in b for b in spec.outputs[0].bits)
    assert spec.outputs[1].name == "fatalErrorCode"


def test_detect_devices_is_multi_response():
    assert spec_by_tool_name()["detect_devices"].multiple_responses


def test_error_codes_load():
    errors = load_error_codes()
    assert errors[0]["enum"] == "ERROR_NONE"
    assert len(errors) > 10
