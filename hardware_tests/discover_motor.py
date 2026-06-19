#!/usr/bin/env python3
"""Probe every RS-485 serial port and report which one(s) have a Gearotons motor.

Tom connected ONE M17 via one of four USB-RS485 adapters; the other three are empty.
This finds it by running the library's device detection on each port and reporting the
unique ID + alias of whatever answers.

Run:
    PYTHONPATH=/Users/sandbox1/servomotor/python_programs python3 discover_motor.py
"""
from __future__ import annotations

import glob
import sys

import servomotor
from servomotor import communication
from servomotor.device_detection import detect_devices_iteratively

DEFAULT_PORTS = sorted(glob.glob("/dev/cu.usbserial-*"))
N_DETECTIONS = 3  # consecutive successful detections the lib requires to trust a result


def probe(port: str) -> list:
    """Return the list of Devices found on `port` (empty if none / no answer)."""
    communication.serial_port = port
    # alias 255 = broadcast/ALL; detection enumerates whoever is on the bus
    servomotor.M3(alias_or_unique_id=255, verbose=0)
    servomotor.open_serial_port()
    try:
        return detect_devices_iteratively(N_DETECTIONS, verbose=False) or []
    finally:
        try:
            servomotor.close_serial_port()
        except Exception:
            pass


def main() -> int:
    ports = sys.argv[1:] or DEFAULT_PORTS
    print(f"Probing {len(ports)} port(s): {ports}\n")
    found = {}
    for port in ports:
        try:
            devices = probe(port)
        except Exception as exc:  # empty adapter -> timeout/serial error; keep going
            print(f"  {port:32s} -> no device ({type(exc).__name__}: {exc})")
            continue
        if devices:
            for d in devices:
                print(f"  {port:32s} -> MOTOR  unique_id=0x{d.unique_id:016X}  alias={d.alias}")
            found[port] = devices
        else:
            print(f"  {port:32s} -> no device (no response)")

    print()
    if not found:
        print("RESULT: no motor detected on any port.")
        return 1
    for port, devices in found.items():
        print(f"RESULT: motor on {port} -> "
              + ", ".join(f"uid=0x{d.unique_id:016X} alias={d.alias}" for d in devices))
    # Emit the first found port on the last line for easy scripting/capture.
    print(f"MOTOR_PORT={next(iter(found))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
