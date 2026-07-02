"""Gearotons M17 servomotor MCP server.

Drive open-source M17 NEMA-17 integrated servomotors from any MCP client (Claude Desktop,
Claude Code, an agent) over RS-485. A thin control layer — it forwards each tool call
straight to the hardware, with no software clamping. Ships with a mock backend so it runs
with no hardware.

``server`` (and its ``mcp`` dependency) is imported lazily via ``main`` so that the
``motors`` module can be used and tested without the MCP SDK installed.
"""

__version__ = "0.2.0"

__all__ = ["main", "__version__"]


def main() -> None:
    """Run the MCP server over stdio. Imports the server (and ``mcp``) lazily."""
    from .server import main as _main

    _main()
