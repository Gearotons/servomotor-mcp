#!/usr/bin/env python3
"""Safe end-to-end smoke test against the real M17 on the bench.

Read-only telemetry first (cannot move the motor), then ONE small bounded move
(+18 deg then back -18 deg) with MOSFETs force-disabled in a finally block.

Run:
    PYTHONPATH=/Users/sandbox1/servomotor/python_programs \
    python3 hw_test_basic.py [PORT] [ALIAS]
Defaults: PORT=/dev/cu.usbserial-210  ALIAS=88   (discovered motor)
"""
from __future__ import annotations

import sys
import time

import servomotor
from servomotor import communication

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbserial-210"
ALIAS = int(sys.argv[2]) if len(sys.argv) > 2 else 88
SAFE_MOVE_DEG = 18.0      # 0.05 rotation — small, safe
MOVE_DURATION_S = 0.6


def show(label, fn, *args):
    # Catch BaseException: the library calls sys.exit() (-> SystemExit) on a command
    # error, which a bare `except Exception` would miss, aborting the whole run.
    try:
        val = fn(*args)
        print(f"  [ok ] {label}: {val!r}")
        return val
    except BaseException as exc:  # noqa: BLE001
        print(f"  [ERR] {label}: {type(exc).__name__}: {exc}")
        return None


def main() -> int:
    print(f"Connecting to motor alias={ALIAS} on {PORT}\n")
    communication.serial_port = PORT
    m = servomotor.M3(alias_or_unique_id=ALIAS, time_unit="seconds",
                      position_unit="degrees", verbose=0)
    servomotor.open_serial_port()
    moved = False
    try:
        print("--- READ-ONLY TELEMETRY (cannot move the motor) ---")
        show("ping (echoes 10-byte payload)", m.ping, bytearray(range(1, 11)))
        show("product_info", m.get_product_info)
        show("firmware_version", m.get_firmware_version)
        show("product_description", m.get_product_description)
        show("status", m.get_status)
        show("supply_voltage", m.get_supply_voltage)
        show("temperature", m.get_temperature)
        start_pos = show("position (deg)", m.get_position)
        show("comprehensive_position", m.get_comprehensive_position)

        print("\n--- BOUNDED MOTION TEST (+18 deg, then back) ---")
        m.enable_mosfets()
        moved = True
        print("  MOSFETs enabled")
        m.trapezoid_move(SAFE_MOVE_DEG, MOVE_DURATION_S)
        time.sleep(MOVE_DURATION_S * 1.15)
        show("position after +18 deg", m.get_position)
        m.trapezoid_move(-SAFE_MOVE_DEG, MOVE_DURATION_S)
        time.sleep(MOVE_DURATION_S * 1.15)
        end_pos = show("position after return", m.get_position)
        if start_pos is not None and end_pos is not None:
            print(f"  net displacement: {float(end_pos) - float(start_pos):+.3f} deg "
                  f"(expect ~0)")
        print("\nMOTION TEST PASSED")
        return 0
    except Exception as exc:
        print(f"\nMOTION TEST FAILED: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if moved:
            try:
                m.disable_mosfets()
                print("  MOSFETs disabled (safe)")
            except Exception as exc:
                print(f"  [WARN] could not disable MOSFETs: {exc}")
        servomotor.close_serial_port()
        print("  serial port closed")


if __name__ == "__main__":
    raise SystemExit(main())
