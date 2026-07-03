"""The MCP server must expose the full toolset with correct schemas (mock backend)."""

import os

import pytest

os.environ["GEAROTONS_MOTOR_BACKEND"] = "mock"  # before server import

from servomotor_mcp import server  # noqa: E402
from servomotor_mcp.catalog import load_catalog  # noqa: E402


@pytest.fixture()
def tools():
    import anyio

    async def _list():
        return await server.mcp.list_tools()

    return {t.name: t for t in anyio.run(_list)}


STATIC_TOOLS = {
    "list_serial_ports", "connect", "disconnect", "detect_devices", "list_motors",
    "move_to", "move_relative", "stop", "get_motor_status", "run_sequence",
}


def test_every_catalog_command_is_a_tool(tools):
    catalog_names = {s.tool_name for s in load_catalog()}
    missing = catalog_names - set(tools) - {"detect_devices"}  # provided natively
    assert not missing, f"catalog commands without a tool: {missing}"
    assert "detect_devices" in tools  # the native version


def test_static_tools_present(tools):
    assert STATIC_TOOLS <= set(tools)


def test_tool_count_covers_full_surface(tools):
    # 48 catalog commands - 1 skipped + 10 static = 57 with library 0.10.0
    assert len(tools) >= 57


def test_generated_tool_schema_types(tools):
    schema = tools["go_to_position"].inputSchema
    props = schema["properties"]
    assert set(props) == {"motor", "position", "duration"}
    assert props["position"]["type"] == "number"
    assert props["duration"]["type"] == "number"
    assert schema["required"] == ["motor", "position", "duration"]


def test_generated_tool_descriptions_carry_units_and_cautions(tools):
    assert "degrees" in tools["go_to_position"].description
    assert "seconds" in tools["go_to_position"].description
    assert "RELATIVE" in tools["trapezoid_move"].description
    assert "brick" in tools["firmware_upgrade"].description
    assert "physical obstruction" in tools["homing"].description


def test_connect_flow_end_to_end_through_tools():
    """Drive the discovery flow exactly as a model would: ports -> connect -> move."""
    import anyio

    async def flow():
        ports = await server.mcp.call_tool("list_serial_ports", {})
        connect = await server.mcp.call_tool("connect", {"port": "MOCK0"})
        move = await server.mcp.call_tool("move_to", {"motor": "42", "degrees": 90})
        raw = await server.mcp.call_tool(
            "go_to_position", {"motor": "42", "position": 180, "duration": 1.0}
        )
        pos = await server.mcp.call_tool("get_position", {"motor": "42"})
        status = await server.mcp.call_tool("get_status", {"motor": "42"})
        return ports, connect, move, raw, pos, status

    ports, connect, move, raw, pos, status = anyio.run(flow)
    assert any("MOCK0" in c.text for c in ports)
    assert any('"alias": 42' in c.text for c in connect)
    assert any('"position_deg": 90.0' in c.text for c in move)
    assert any('"success": true' in c.text for c in raw)
    assert any('"position": 180.0' in c.text for c in pos)
    assert any("fatal_error_code" in c.text for c in status)


def test_not_connected_error_is_actionable():
    import anyio

    fresh = server._bus.__class__()
    with pytest.raises(Exception, match="list_serial_ports"):
        fresh.list_motors()
