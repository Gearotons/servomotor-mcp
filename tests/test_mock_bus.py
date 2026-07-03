"""Backend behavior against the in-memory MockBus (no hardware, no serial)."""

import pytest

from servomotor_mcp.motors import BROADCAST, MockBus, NotConnectedError, get_bus


@pytest.fixture()
def bus():
    b = MockBus()
    b.connect(port="MOCK0")
    return b


def test_get_bus_respects_env(monkeypatch):
    monkeypatch.setenv("GEAROTONS_MOTOR_BACKEND", "mock")
    assert isinstance(get_bus(), MockBus)


def test_list_ports_shows_simulated_adapters():
    b = MockBus()
    ports = b.list_ports()
    assert [p["device"] for p in ports] == ["MOCK0", "MOCK1"]
    assert all(p["likely_usb_serial_adapter"] for p in ports)
    assert not any(p["connected"] for p in ports)


def test_connect_autodetects_motors():
    b = MockBus()
    result = b.connect(port="MOCK0")
    assert result["connected_port"] == "MOCK0"
    assert {m["alias"] for m in result["motors"]} == {42, 43}
    assert all(len(m["unique_id"]) == 16 for m in result["motors"])


def test_connect_to_empty_bus_notes_no_motors():
    b = MockBus()
    result = b.connect(port="MOCK1")
    assert result["motors"] == []
    assert "No motors" in result["note"]


def test_connect_unknown_port_raises_with_options():
    b = MockBus()
    with pytest.raises(RuntimeError, match="MOCK0"):
        b.connect(port="/dev/nonexistent")


def test_failed_connect_keeps_existing_connection(bus):
    with pytest.raises(RuntimeError):
        bus.connect(port="/dev/nonexistent")
    assert bus.connected_port == "MOCK0"
    assert bus.list_motors()  # still fully usable


def test_tools_require_connection():
    b = MockBus()
    with pytest.raises(NotConnectedError):
        b.list_motors()
    with pytest.raises(NotConnectedError):
        b.detect()


def test_addressing_by_alias_uid_and_broadcast(bus):
    assert bus.resolve(42) == 42
    assert bus.resolve("42") == 42
    assert bus.resolve("0123456789ABCDEF") == 0x0123456789ABCDEF
    assert bus.resolve("all") == BROADCAST
    assert bus.resolve("X") == ord("X")
    with pytest.raises(ValueError):
        bus.resolve("not a motor")


def test_alias_and_uid_hit_the_same_motor(bus):
    bus.move_to("42", 90.0)
    status = bus.motor_status("0123456789ABCDEF")
    assert status["position_deg"] == 90.0


def test_move_to_and_relative(bus):
    s = bus.move_to("42", 360.0)  # full turn, no clamp
    assert s["position_deg"] == 360.0
    s = bus.move_relative("42", -90.0)
    assert s["position_deg"] == 270.0
    s = bus.move_to("42", 1080.0)  # multi-turn stays allowed
    assert s["position_deg"] == 1080.0


def test_execute_generic_command(bus):
    result = bus.execute("42", "get_position", [])
    assert result["command"] == "Get position"
    assert result["response"]["position"] == 0.0
    bus.execute("42", "enable_mosfets", [])
    result = bus.execute("42", "go_to_position", [45.0, 1.0])
    assert result["response"] == {"success": True}
    assert bus.execute("42", "get_position", [])["response"]["position"] == 45.0


def test_execute_wrong_arg_count(bus):
    with pytest.raises(ValueError, match="takes 2 parameter"):
        bus.execute("42", "go_to_position", [45.0])


def test_execute_unknown_command(bus):
    with pytest.raises(ValueError, match="Unknown command"):
        bus.execute("42", "warp_drive", [])


def test_status_decoding_flags_and_no_error(bus):
    bus.execute("42", "enable_mosfets", [])
    result = bus.execute("42", "get_status", [])
    assert result["decoded"]["fatal_error_code"] == 0
    assert any("MOSFETs" in f for f in result["decoded"]["active_flags"])


def test_ping_pads_and_echoes(bus):
    result = bus.execute("42", "ping", ["hello"])
    assert result["response"]["responsePayload"]["text"] == "hello"


def test_system_reset_rezeros_and_disables(bus):
    bus.move_to("42", 90.0)
    result = bus.execute("42", "system_reset", [])
    assert "rebooted" in result["response"]["note"]
    assert bus.motor_status("42")["position_deg"] == 0.0


def test_broadcast_returns_no_responses(bus):
    result = bus.execute("all", "emergency_stop", [])
    assert "broadcast" in result["response"]["note"]


def test_stop_all_and_one(bus):
    assert bus.stop()["stopped"] == "all"
    assert bus.stop("42")["stopped"] == "42"


def test_list_motors_snapshots(bus):
    motors = bus.list_motors()
    assert len(motors) == 2
    for m in motors:
        assert set(m) >= {"alias", "unique_id", "position_deg", "voltage_v", "temperature_c", "status"}


def test_detect_after_moves_rezeros(bus):
    bus.move_to("42", 90.0)
    bus.detect()
    assert bus.motor_status("42")["position_deg"] == 0.0


def test_disconnect_forgets_bus_state(bus):
    bus.disconnect()
    assert bus.connected_port is None
    with pytest.raises(NotConnectedError):
        bus.list_motors()


def test_unknown_simulated_motor(bus):
    with pytest.raises(RuntimeError, match="No simulated motor"):
        bus.motor_status("99")


def test_multimove_mixed_unit_conversion(bus):
    # bit 0 = 0 -> acceleration move (deg/s^2), bit 1 = 1 -> velocity move (deg/s).
    # Factors from unit_conversions_M3.json; durations are seconds -> 31250 timesteps/s.
    count, types, move_list = bus._prepare_multimove([2, 0b10, [[100, 1.0], [50, 2.0]]])
    assert (count, types) == (2, 0b10)
    converted = eval(move_list)
    assert converted[0] == [round(100 * 156.37498706147557), 31250]   # acceleration
    assert converted[1] == [round(50 * 305419.8966044445), 62500]     # velocity
    # And the full path through execute() succeeds against the mock.
    result = bus.execute("42", "multimove", [2, 0b10, [[100, 1.0], [50, 2.0]]])
    assert result["response"] == {"success": True}
