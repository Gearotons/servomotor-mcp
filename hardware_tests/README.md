# Hardware tests — Gearotons M17 MCP server

Scripts that validate the MCP server against a **real M17** over RS-485. All passed on
2026-07-03 against a physical motor (fw 0.15.3.0, alias 88) — results in `RESULTS.txt`.

## Setup

```bash
pip install -e '..[serial,dev]'   # the MCP package + the servomotor library + mcp SDK
cd hardware_tests
```

Nothing else to configure: the scripts (like the server) discover ports and detect motors.
The suite scripts default to the bench setup (`/dev/cu.usbserial-210`, alias 88) but take
the port / unique ID as arguments.

## The tests

| Script | What it proves |
|---|---|
| `hw_discover.py` | Port enumeration + connect/detect sweep across every USB adapter: motors are found where they really are, empty buses report gracefully. |
| `hw_suite.py [PORT] [UID]` | The deep pass: every read-only firmware command, high-level moves (full turn, relative, unique-ID addressing), raw queued moves with `get_n_queued_items` polling, `multimove` (mixed-unit conversion), vibrate/identify/time/zero, emergency stop, `system_reset` recovery, the sequence engine, and the error paths (absent motor, wrong arg count). ~50 checks. |
| `hw_mcp_stdio_session.py [PORT] [EMPTY_PORT]` | A real stdio MCP session (official `mcp` client → subprocess server, exactly like Claude Desktop): clean JSON-RPC handshake with the serial backend, 57 tools listed, discovery flow, moves, graceful wrong-port behavior, failed connect keeps the old connection. |

```bash
python3 hw_discover.py
python3 hw_suite.py
python3 hw_mcp_stdio_session.py
```

## Verified results (2026-07-03, physical M17)

- **Discovery:** 4 USB-RS485 adapters enumerated (CP2102N); motor found ONLY on the bus
  that truly has one — unique_id `99856389A2B46555`, alias 88; the 3 empty adapters
  return the "No motors responded" note.
- **hw_suite.py: 49/49 passed** — includes fw `0.15.3.0`, 20.0 V supply, 41 °C, ping echo,
  full 360° turn (settled 360.0°), queue-drain polling (settled 89.9998°), multimove
  accelerate/decelerate with no fatal error, reset recovery, and actionable timeout text
  for a motor that isn't there.
- **hw_mcp_stdio_session.py: 10/10 passed** — stdout stays pure JSON-RPC (library chatter
  routed to stderr), tools = 57 (47 catalog + 10 high-level).
- Also verified through **`uvx --from '<pkg>[serial]' servomotor-mcp`** — the exact launch
  mechanism Claude Desktop uses.

## Notes for multi-motor buses (next test phase)

Detection merges several rounds because the firmware answers in randomized time slots;
with many motors on one bus, raise `detect_devices(attempts=...)`. Address motors by
unique ID when aliases might collide.

## Unit tests (no hardware)

```bash
GEAROTONS_MOTOR_BACKEND=mock python3 -m pytest -q ../tests
```
