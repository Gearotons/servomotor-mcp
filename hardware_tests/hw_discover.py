#!/usr/bin/env python3
"""Sweep every USB serial adapter and report which bus(es) actually hold motors.

This is the discovery flow an MCP client runs, driven directly against the backend:
list ports -> connect+detect on each USB adapter -> report unique ID + alias of whatever
answers. Empty adapters must fail gracefully with the "No motors" note.

Run (with the [serial] extra installed):
    python3 hw_discover.py
"""
from __future__ import annotations

import json

from servomotor_mcp.motors import get_bus


def main() -> None:
    bus = get_bus()
    ports = bus.list_ports()
    print(json.dumps(ports, indent=1))
    for p in ports:
        if not p["likely_usb_serial_adapter"]:
            continue
        try:
            result = bus.connect(port=p["device"], detect=True, attempts=2)
            motors = result.get("motors", [])
            print(f"{p['device']}: {json.dumps(motors) if motors else result.get('note')}")
        except Exception as exc:
            print(f"{p['device']}: ERROR {exc}")
    bus.disconnect()


if __name__ == "__main__":
    main()
