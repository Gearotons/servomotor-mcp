# servomotor-mcp

**Drive open-source [Gearotons M17](https://gearotons.com) servomotors from natural language.**

An [MCP](https://modelcontextprotocol.io) server that exposes the M17 — a NEMA-17
integrated, closed-loop, RS-485 servomotor — as a small set of safe, high-level tools.
Connect it to Claude Desktop, Claude Code, or any MCP client and control real motors by
just *asking*:

> "Home everything, then draw a square with the X and Y axes."

It ships with a **mock backend**, so you can try the whole thing with **no hardware**.

> The first servomotor with an official MCP server. Open hardware, open firmware, open
> software — and now an open, AI-native control interface.

---

## Quickstart (no hardware, ~2 minutes)

```bash
# Run the server directly with uv (recommended):
uvx --from servomotor-mcp servomotor-mcp

# or install it:
pip install servomotor-mcp
servomotor-mcp
```

Then add it to **Claude Desktop** — copy the block from
[`examples/claude_desktop_config.json`](examples/claude_desktop_config.json) into your
`claude_desktop_config.json`, restart Claude Desktop, and ask:
*"What motors do you have connected?"* See [`examples/demo_prompts.md`](examples/demo_prompts.md)
for the full scripted demo.

## Drive real motors

Plug an M17 (or a daisy-chain of them) into a USB↔RS-485 adapter and switch the backend:

```bash
pip install 'servomotor-mcp[serial]'   # pulls in the Gearotons servomotor library
GEAROTONS_MOTOR_BACKEND=serial \
GEAROTONS_SERIAL_PORT=/dev/ttyUSB0 \
servomotor-mcp
```

## Tools

| Tool | What it does |
|---|---|
| `list_motors` | Discover motors on the bus + positions (call first). |
| `move_to` | Move a motor to an absolute angle (closed-loop). |
| `move_relative` | Nudge a motor by a delta. |
| `trapezoid_move` | Smooth accel/decel move (best for arms/plotters). |
| `home` | Home one or all motors. |
| `get_status` | Position / moving / voltage / errors. |
| `stop` | Halt one or all motors. |
| `reset` | Recover a motor from a latched fault (firmware system reset, ~2 s). |
| `run_sequence` | Run a choreographed sequence ("draw a square"). |

## Safety rails (in the server, not the model)

The LLM can hallucinate a tool call; these make that safe — they run on every request:

- **Alias allow-list** — only configured motors can be driven.
- **Position limits** — absolute/relative targets are clamped to a per-motor software
  range, so a bad command can't drive an axis into a hard stop.
- **Speed clamp** — requested speeds are capped.

Clamps are *reported back* to the model (in `safety_notes`) rather than silently applied,
so it can see what actually happened and adjust. Configure via env:

```bash
GEAROTONS_MOTOR_ALIASES="x,y,z"
GEAROTONS_LIMITS='{"x":{"min_deg":-180,"max_deg":180,"max_speed":300},"z":{"min_deg":0,"max_deg":90}}'
```

## How it works

```
natural language → Claude → MCP tool calls → this server → RS-485 → M17 motors
```

The server is a thin, safety-checked wrapper over the Gearotons `servomotor` Python
library (high-level, unit-aware commands — no DIR/STEP timing). The same intents run
against the mock backend for development and CI.

## Develop / test

```bash
pip install -e '.[dev]'
pytest                      # safety + mock-bus tests, no hardware needed
GEAROTONS_MOCK_SIM_SECONDS=0.4 servomotor-mcp   # lifelike timing for demos
```

## Status

- ✅ MCP server, full tool surface, safety rails, mock backend — done; 16 unit tests pass.
- ✅ `SerialBus` real-hardware backend — **verified against a physical M17** (fw 0.15.0.0):
  discovery, telemetry, closed-loop moves at **0.000° repeatability**, and a live safety
  clamp (a 200° command on a ±90° motor stopped at 90°). See [`hardware_tests/`](hardware_tests/).
- 🔜 Live FastMCP-over-stdio run with Claude Desktop needs a Python ≥3.10 host (tool logic
  already hardware-verified); plus the physical demo build + video. See [demo spec](../SPEC.md).

## License

MIT. Hardware, firmware, and software for the M17 are open-source —
see [github.com/tomrodinger/servomotor](https://github.com/tomrodinger/servomotor).
