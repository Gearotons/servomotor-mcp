"""End-to-end stdio MCP session against the reworked server, real motor on the bus.

Launches the server exactly like Claude Desktop does (subprocess, stdio transport) and
drives the discovery flow a model would: list tools -> list ports -> connect (auto-detect)
-> move -> raw command -> status -> wrong-port behavior."""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

VENV_PY = sys.executable
PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbserial-210"
EMPTY_PORT = sys.argv[2] if len(sys.argv) > 2 else "/dev/cu.usbserial-110"


def text(result):
    return "\n".join(c.text for c in result.content if hasattr(c, "text"))


async def main():
    params = StdioServerParameters(
        command=VENV_PY, args=["-m", "servomotor_mcp"],
        env={"PATH": "/usr/bin:/bin"},
    )
    ok = 0
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("initialize: clean handshake")

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            assert len(names) >= 57, f"only {len(names)} tools"
            for t in ("list_serial_ports", "connect", "move_to", "go_to_position",
                      "multimove", "firmware_upgrade", "get_communication_statistics"):
                assert t in names, t
            print(f"list_tools: {len(names)} tools exposed"); ok += 1

            r = await session.call_tool("list_serial_ports", {})
            assert PORT in text(r)
            print("list_serial_ports: sees the adapters"); ok += 1

            r = await session.call_tool("connect", {"port": EMPTY_PORT, "detect_attempts": 1})
            assert "No motors" in text(r)
            print("connect(empty adapter): graceful 'no motors' note"); ok += 1

            r = await session.call_tool("connect", {"port": PORT, "detect_attempts": 2})
            payload = text(r)
            assert '"alias": 88' in payload and "99856389A2B46555" in payload
            print("connect(right adapter): auto-detected motor 88"); ok += 1

            r = await session.call_tool("move_to", {"motor": "88", "degrees": 360, "speed_dps": 360})
            assert '"position_deg": 360' in text(r)
            print("move_to: full 360 turn, settled"); ok += 1

            r = await session.call_tool("get_temperature", {"motor": "88"})
            assert '"temperature"' in text(r)
            print("raw get_temperature via generated tool"); ok += 1

            r = await session.call_tool("run_sequence", {"steps": [
                {"action": "move_to", "motor": "88", "degrees": 0, "speed_dps": 360},
                {"action": "command", "motor": "88", "name": "identify", "params": []},
            ]})
            assert '"position_deg": 0' in text(r)
            print("run_sequence incl. raw command step"); ok += 1

            r = await session.call_tool("get_motor_status", {"motor": "88"})
            assert '"fatal_error_code": 0' in text(r)
            print("get_motor_status: healthy"); ok += 1

            r = await session.call_tool("connect", {"port": "/dev/does-not-exist"})
            assert r.isError and "Available ports" in text(r)
            assert "Still connected" in text(r)
            print("connect(bad port): error lists ports, old connection kept"); ok += 1

            r = await session.call_tool("stop", {})
            assert '"stopped": "all"' in text(r)
            print("stop all (still connected after failed connect)"); ok += 1

            await session.call_tool("disconnect", {})
            print("disconnect: clean")

    print(f"\nSTDIO MCP SESSION: all {ok} checks passed")


asyncio.run(main())
