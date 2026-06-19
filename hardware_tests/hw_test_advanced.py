#!/usr/bin/env python3
"""Advanced hardware tests against the real M17 via SerialBus.

1. Identify    — blink the motor's LED (visible confirmation at the bench).
2. Repeatability — move to N random absolute targets, measure closed-loop error.
3. Demo routine — a short "wave" choreography (the kind of thing the AI demo runs).

Run:
    PYTHONPATH=../src:/Users/sandbox1/servomotor/python_programs python3 hw_test_advanced.py
"""
from __future__ import annotations

import random
import sys
import time

from servomotor_mcp.motors import SerialBus

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbserial-210"
DEVICE_ALIAS = int(sys.argv[2]) if len(sys.argv) > 2 else 88
NAME = "x"
N_RANDOM = 12
RANGE_DEG = 80.0
TOL_DEG = 0.5  # closed-loop accuracy tolerance


def main() -> int:
    random.seed(12345)  # deterministic targets so runs are comparable
    bus = SerialBus(port=PORT, motor_map={NAME: DEVICE_ALIAS})
    m = bus._m[NAME]  # underlying M3 for raw commands not on the bus interface
    errors = []
    try:
        print("--- 1. identify (LED should blink on the motor) ---")
        try:
            m.identify()
            print("  identify() sent — check the motor LED")
            time.sleep(1.0)
        except BaseException as exc:  # noqa: BLE001
            print(f"  identify skipped: {type(exc).__name__}: {exc}")

        print(f"\n--- 2. repeatability: {N_RANDOM} random targets in ±{RANGE_DEG}° ---")
        for i in range(N_RANDOM):
            target = round(random.uniform(-RANGE_DEG, RANGE_DEG), 1)
            state = bus.move_to(NAME, target)
            err = abs(state.position_deg - target)
            errors.append(err)
            flag = "ok" if err <= TOL_DEG else "OVER TOL"
            print(f"  [{i+1:2d}] target={target:7.1f}°  reached={state.position_deg:7.2f}°  "
                  f"err={err:.3f}°  [{flag}]")
        mean_err = sum(errors) / len(errors)
        max_err = max(errors)
        print(f"\n  mean error={mean_err:.3f}°   max error={max_err:.3f}°   "
              f"tolerance={TOL_DEG}°")

        print("\n--- 3. demo 'wave' routine ---")
        bus.move_to(NAME, 0)
        for deg in (25, -25, 20, -20, 12, -12, 0):
            s = bus.move_to(NAME, deg, speed=240)
            print(f"  wave -> {s.position_deg:6.2f}°")

        passed = max_err <= TOL_DEG
        print(f"\nADVANCED TEST {'PASSED' if passed else 'FAILED (accuracy)'}  "
              f"(max err {max_err:.3f}° vs tol {TOL_DEG}°)")
        return 0 if passed else 1
    except Exception as exc:
        print(f"\nADVANCED TEST ERROR: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        bus.close()
        print("  bus closed (MOSFETs disabled, port closed)")


if __name__ == "__main__":
    raise SystemExit(main())
