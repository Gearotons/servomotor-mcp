#!/usr/bin/env python3
"""Extended hardware coverage against the real M17 (raw M3 commands).

- get_max_pid_error : closed-loop tightness (real encoder-error numbers)
- move_with_velocity: a bounded constant-velocity move (auto-stops after its time)
- throughput        : 20 absolute moves, measure moves/sec
- enable/disable     : reliability over several cycles

Run:
    PYTHONPATH=../src:/Users/sandbox1/servomotor/python_programs python3 hw_test_extended.py
"""
from __future__ import annotations

import random
import sys
import time

from servomotor_mcp.motors import SerialBus

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbserial-210"
DEVICE_ALIAS = int(sys.argv[2]) if len(sys.argv) > 2 else 88
NAME = "x"


def safe(label, fn, *a):
    try:
        v = fn(*a)
        print(f"  [ok ] {label}: {v!r}")
        return v
    except BaseException as exc:  # noqa: BLE001
        print(f"  [ERR] {label}: {type(exc).__name__}: {exc}")
        return None


def main() -> int:
    random.seed(7)
    bus = SerialBus(port=PORT, motor_map={NAME: DEVICE_ALIAS})
    m = bus._m[NAME]
    try:
        print("--- 1. enable + get_max_pid_error (closed-loop error, in degrees) ---")
        bus._ensure_enabled(NAME)
        bus.move_to(NAME, 0)
        safe("max_pid_error [min,max]", m.get_max_pid_error)

        print("\n--- 2. bounded velocity move (~60 deg/s for 0.4 s, then auto-stop) ---")
        p0 = float(safe("position before", m.get_position))
        try:
            m.move_with_velocity(60, 0.4)   # degrees/sec for seconds; stops itself
            time.sleep(0.6)
            p1 = float(safe("position after", m.get_position))
            print(f"  velocity-move displacement: {p1 - p0:+.2f}° (expected ~+24°)")
        except BaseException as exc:  # noqa: BLE001
            print(f"  velocity move skipped: {type(exc).__name__}: {exc}")
        bus.move_to(NAME, 0)  # recenter

        print("\n--- 3. throughput: 20 absolute moves, measure moves/sec ---")
        t0 = time.time()
        worst = 0.0
        for i in range(20):
            tgt = round(random.uniform(-70, 70), 1)
            s = bus.move_to(NAME, tgt)
            worst = max(worst, abs(s.position_deg - tgt))
        dt = time.time() - t0
        print(f"  20 moves in {dt:.1f}s = {20/dt:.2f} moves/s; worst position error {worst:.3f}°")

        print("\n--- 4. enable/disable reliability (5 cycles) ---")
        ok = 0
        for i in range(5):
            try:
                bus._safe(m.enable_mosfets)
                bus._safe(m.disable_mosfets)
                ok += 1
            except BaseException as exc:  # noqa: BLE001
                print(f"  cycle {i} failed: {exc}")
        print(f"  {ok}/5 enable+disable cycles clean")

        passed = worst <= 0.5 and ok == 5
        print(f"\nEXTENDED TEST {'PASSED' if passed else 'CHECK RESULTS'}")
        return 0 if passed else 1
    except Exception as exc:
        print(f"\nEXTENDED TEST ERROR: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        bus.close()
        print("  bus closed")


if __name__ == "__main__":
    raise SystemExit(main())
