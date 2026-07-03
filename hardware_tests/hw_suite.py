"""Deep hardware pass for the reworked servomotor-mcp against the bench M17 (alias 88)."""
import json
import sys
import time

from servomotor_mcp.motors import get_bus
from servomotor_mcp.sequencer import run_sequence_steps

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbserial-210"
UID = sys.argv[2] if len(sys.argv) > 2 else "99856389A2B46555"

bus = get_bus()
passed, failed = [], []


def check(name, fn, predicate=lambda r: True, show=True):
    try:
        r = fn()
        assert predicate(r), f"predicate failed on {r!r}"
        passed.append(name)
        if show:
            print(f"PASS {name}: {json.dumps(r, default=str)[:220]}")
        else:
            print(f"PASS {name}")
    except Exception as e:
        failed.append((name, repr(e)))
        print(f"FAIL {name}: {e!r}")


def expect_error(name, fn, needle):
    try:
        r = fn()
        failed.append((name, f"no error raised, got {r!r}"))
        print(f"FAIL {name}: expected error, got result")
    except Exception as e:
        if needle in str(e):
            passed.append(name)
            print(f"PASS {name}: raised '{str(e)[:120]}'")
        else:
            failed.append((name, f"wrong error: {e!r}"))
            print(f"FAIL {name}: wrong error {e!r}")


# --- connection & discovery -----------------------------------------------------------
check("connect+detect", lambda: bus.connect(port=PORT, attempts=2),
      lambda r: any(m["alias"] == 88 for m in r["motors"]))
check("list_motors", bus.list_motors,
      lambda ms: ms[0]["unique_id"] == UID and 10 < ms[0]["voltage_v"] < 30)

# --- every read-only command ----------------------------------------------------------
RO = [
    ("get_position", []),
    ("get_hall_sensor_position", []),
    ("get_comprehensive_position", []),
    ("get_status", []),
    ("get_supply_voltage", []),
    ("get_temperature", []),
    ("get_n_queued_items", []),
    ("get_current_time", []),
    ("get_product_info", []),
    ("get_product_description", []),
    ("get_firmware_version", []),
    ("get_product_specs", []),
    ("get_max_pid_error", []),
    ("get_debug_values", []),
    ("get_hall_sensor_statistics", []),
    ("get_communication_statistics", [0]),
]
for name, args in RO:
    check(f"raw {name}", lambda n=name, a=args: bus.execute("88", n, a))

check("ping echo", lambda: bus.execute("88", "ping", ["hello mcp"]),
      lambda r: r["response"]["responsePayload"]["text"].startswith("hello mcp"))

# --- status decode sanity ---------------------------------------------------------------
check("status decoded, no fatal error", lambda: bus.execute("88", "get_status", []),
      lambda r: r["decoded"]["fatal_error_code"] == 0)

# --- high-level motion ------------------------------------------------------------------
check("move_to 360 (full turn)", lambda: bus.move_to("88", 360.0),
      lambda s: abs(s["position_deg"] - 360.0) < 2.0)
check("move_relative -90", lambda: bus.move_relative("88", -90.0),
      lambda s: abs(s["position_deg"] - 270.0) < 2.0)
check("address by unique id", lambda: bus.move_to(UID, 0.0, 240.0),
      lambda s: abs(s["position_deg"]) < 2.0)

# --- raw motion + queue polling ---------------------------------------------------------
check("raw enable_mosfets", lambda: bus.execute("88", "enable_mosfets", []))
check("raw go_to_position 90 over 1.5s", lambda: bus.execute("88", "go_to_position", [90.0, 1.5]))
def poll_queue():
    for _ in range(40):
        n = bus.execute("88", "get_n_queued_items", [])["response"]["queueSize"]
        if n == 0:
            return bus.execute("88", "get_position", [])["response"]["position"]
        time.sleep(0.15)
    raise TimeoutError("queue never drained")
check("queue drains, position 90", poll_queue, lambda p: abs(p - 90.0) < 2.0)
check("raw trapezoid_move (relative) -45", lambda: bus.execute("88", "trapezoid_move", [-45.0, 1.0]))
time.sleep(1.3)
check("position now 45", lambda: bus.execute("88", "get_position", [])["response"]["position"],
      lambda p: abs(p - 45.0) < 2.0)

# --- multimove (accel up then down -> standstill) ---------------------------------------
check("multimove accel +/-", lambda: bus.execute(
    "88", "multimove", [2, 0b00, [[200.0, 1.0], [-200.0, 1.0]]]))
time.sleep(2.3)
check("multimove no fatal error", lambda: bus.execute("88", "get_status", []),
      lambda r: r["decoded"]["fatal_error_code"] == 0)

# --- misc safe writes -------------------------------------------------------------------
check("vibrate on", lambda: bus.execute("88", "vibrate", [1]))
time.sleep(1.0)
check("vibrate off", lambda: bus.execute("88", "vibrate", [0]))
check("identify (LED)", lambda: bus.execute("88", "identify", []))
check("reset_time", lambda: bus.execute("88", "reset_time", []))
check("get_current_time small", lambda: bus.execute("88", "get_current_time", []),
      lambda r: r["response"]["currentTime"] < 31250 * 60)
check("set_maximum_velocity 600dps", lambda: bus.execute("88", "set_maximum_velocity", [600.0]))
check("set_maximum_acceleration", lambda: bus.execute("88", "set_maximum_acceleration", [10000.0]))
check("zero_position", lambda: bus.execute("88", "zero_position", []))
check("position is 0 after zero", lambda: bus.execute("88", "get_position", [])["response"]["position"],
      lambda p: abs(p) < 1.0)
check("emergency_stop (raw)", lambda: bus.execute("88", "emergency_stop", []))
check("stop() high-level broadcast", lambda: bus.stop(), lambda r: r["stopped"] == "all")
check("disable_mosfets", lambda: bus.execute("88", "disable_mosfets", []))

# --- system reset recovery ---------------------------------------------------------------
check("system_reset", lambda: bus.execute("88", "system_reset", []),
      lambda r: "rebooted" in r["response"]["note"])
check("alive after reset", lambda: bus.execute("88", "get_status", []),
      lambda r: r["decoded"]["fatal_error_code"] == 0)

# --- sequence engine ----------------------------------------------------------------------
check("run_sequence square-ish", lambda: run_sequence_steps(bus, [
    {"action": "move_to", "motor": "88", "degrees": 90, "speed_dps": 240},
    {"action": "wait", "seconds": 0.2},
    {"action": "move_relative", "motor": "88", "degrees": -45},
    {"action": "command", "motor": "88", "name": "get_position", "params": []},
    {"action": "stop"},
]) or bus.execute("88", "get_position", [])["response"]["position"],
      lambda p: abs(p - 45.0) < 2.0)

# --- error paths ---------------------------------------------------------------------------
expect_error("missing motor 99 times out helpfully",
             lambda: bus.execute("99", "get_position", []), "detect_devices")
expect_error("wrong arg count", lambda: bus.execute("88", "go_to_position", [1.0]), "parameter")

check("re-detect finds motor again", lambda: bus.detect(attempts=2),
      lambda ms: ms and ms[0]["alias"] == 88)
check("disconnect", bus.disconnect, lambda r: r["disconnected"] == PORT)

print(f"\n=== {len(passed)} passed, {len(failed)} failed ===")
for name, err in failed:
    print("FAILED:", name, "->", err)
sys.exit(1 if failed else 0)
