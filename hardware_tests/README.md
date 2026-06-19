# Hardware tests — Gearotons M17 MCP server

Scripts that validate the MCP server's motor backend against a **real M17** over RS-485.
All four passed on 2026-06-08 against a physical motor (fw 0.15.0.0) — see results below and
`../../../logs/hardware-2026-06-08.md`.

## Setup

`pyserial` is the only runtime dep for these (already present on the test machine). Point
`PYTHONPATH` at the open-source `servomotor` library + the MCP package `src/`:

```bash
export SERVOMOTOR=/Users/sandbox1/servomotor/python_programs   # or: pip install servomotor
export PKG=../src
cd hardware_tests
```

The motor was auto-discovered on `/dev/cu.usbserial-210`, device **alias 88**. Adjust the
port/alias args if yours differ.

## The tests

| Script | What it proves | Needs |
|---|---|---|
| `discover_motor.py` | Finds which of the connected RS-485 adapters has a motor; reports unique ID + alias. | servomotor |
| `hw_test_basic.py` | Read-only telemetry (product/fw/status/voltage/temp/position) + one bounded ±18° move. | servomotor |
| `hw_test_serialbus.py` | The **MCP tool code path** (SafetyPolicy clamp → `SerialBus`), incl. a live safety clamp. | servomotor + `src/` |
| `hw_test_advanced.py` | `identify` LED blink + 12-target repeatability + a "wave" demo routine. | servomotor + `src/` |
| `hw_test_extended.py` | PID-error readout, bounded velocity move, throughput timing, enable/disable reliability. | servomotor + `src/` |
| `hw_test_sequence.py` | The `run_sequence` engine (the "draw"/"wave" path): a draw routine, a sequence-level clamp, and abort-on-disallowed-motor. | servomotor + `src/` |
| `hw_test_endurance.py` | N bounded moves with temperature/voltage/error sampling — reliability + thermal data. | servomotor + `src/` |

```bash
PYTHONPATH=$SERVOMOTOR        python3 discover_motor.py
PYTHONPATH=$SERVOMOTOR        python3 hw_test_basic.py
PYTHONPATH=$PKG:$SERVOMOTOR   python3 hw_test_serialbus.py
PYTHONPATH=$PKG:$SERVOMOTOR   python3 hw_test_advanced.py
PYTHONPATH=$PKG:$SERVOMOTOR   python3 hw_test_extended.py
PYTHONPATH=$PKG:$SERVOMOTOR   python3 hw_test_sequence.py
```

## Verified results (2026-06-08, physical M17)

- **Discovery:** motor on `/dev/cu.usbserial-210`, unique_id `0x99856389A2B46555`, alias 88;
  other three adapters empty.
- **Telemetry:** M17, fw **0.15.0.0**, status `[0,0]` (healthy), supply **20.0 V**, **35 °C**.
- **Bounded move:** +18° → read back 17.9999°, return → 0.000° net drift.
- **SerialBus + safety:** absolute moves exact; **live clamp** — commanded 200° on a ±90°-
  limited motor → physically stopped at **90.00°** with the clamp note surfaced. ✅
- **Repeatability:** 12 random targets across ±80° → **0.000° mean & max error** (tol 0.5°).
- **Demo routine + LED identify:** clean.
- **Extended:** 20-move throughput 2.87 moves/s @ 0.000° worst error; 5/5 enable/disable
  cycles clean. (Findings: `move_with_velocity` needs unit calibration before exposing a spin
  tool; `get_max_pid_error` returned reset sentinels — read it after a move run for a real
  number. Neither affects the 8 shipped MCP tools.)

Every test force-disables the MOSFETs and closes the port in a `finally` block.

## Unit tests (no hardware)

The mock backend + safety rails + sequencer are covered by `../tests/` (21 tests):

```bash
PYTHONPATH=../src python3 -m pytest -q ../tests   # 21 passed
```

## Note on the live MCP-over-stdio test

Running the actual FastMCP server end-to-end (MCP client → server → motor) needs the `mcp`
SDK, which requires **Python ≥3.10**; the test machine has 3.9, so that step is deferred to
a 3.10+ host (e.g. the dev machine). It is low-risk: `hw_test_serialbus.py` already exercises
the identical tool logic (clamp → `SerialBus`) on hardware — only generic FastMCP transport
plumbing is left unverified.
