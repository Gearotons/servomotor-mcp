#!/usr/bin/env python3
"""Endurance / thermal characterization of the real M17.

Runs N bounded absolute moves, sampling temperature, supply voltage, and position error
periodically. Produces real reliability data (drift, thermal rise) — not a pass/fail gate.

Run:
    PYTHONPATH=../src:/Users/sandbox1/servomotor/python_programs python3 hw_test_endurance.py [N]
"""
from __future__ import annotations

import random
import sys
import time

from servomotor_mcp.motors import SerialBus

PORT = "/dev/cu.usbserial-210"
DEVICE_ALIAS = 88
NAME = "x"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 80
SAMPLE_EVERY = 20


def main() -> int:
    random.seed(2026)
    bus = SerialBus(port=PORT, motor_map={NAME: DEVICE_ALIAS})
    m = bus._m[NAME]
    worst = 0.0
    t_start = time.time()
    try:
        v0 = float(bus._safe(m.get_supply_voltage)) / 1000.0
        temp0 = float(bus._safe(m.get_temperature))
        print(f"start: {v0:.1f} V, {temp0:.0f} °C")
        print(f"running {N} bounded moves (±70°), sampling every {SAMPLE_EVERY}...\n")
        for i in range(1, N + 1):
            tgt = round(random.uniform(-70, 70), 1)
            s = bus.move_to(NAME, tgt)
            worst = max(worst, abs(s.position_deg - tgt))
            if i % SAMPLE_EVERY == 0:
                temp = float(bus._safe(m.get_temperature))
                volts = float(bus._safe(m.get_supply_voltage)) / 1000.0
                print(f"  move {i:3d}/{N}: temp={temp:.0f}°C  v={volts:.1f}V  "
                      f"worst_err={worst:.3f}°")
        dt = time.time() - t_start
        temp1 = float(bus._safe(m.get_temperature))
        bus.move_to(NAME, 0)
        print(f"\ndone: {N} moves in {dt:.0f}s ({N/dt:.2f}/s), "
              f"temp {temp0:.0f}->{temp1:.0f}°C (rise {temp1-temp0:+.0f}), "
              f"worst position error {worst:.3f}°")
        # Informational thresholds: closed loop should stay tight, motor shouldn't cook.
        print("ENDURANCE TEST: " + ("CLEAN" if (worst <= 0.5 and temp1 < 70) else "REVIEW"))
        return 0
    except Exception as exc:
        print(f"\nENDURANCE ERROR: {type(exc).__name__}: {exc}")
        return 1
    finally:
        bus.close()
        print("  bus closed")


if __name__ == "__main__":
    raise SystemExit(main())
