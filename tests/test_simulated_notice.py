"""The simulator must always announce itself, so nobody with real hardware ends up on it unknowingly."""
import importlib

from servomotor_mcp import motors
from servomotor_mcp.motors import MockBus, SerialBus, get_bus


def test_auto_without_library_uses_simulator_and_says_so(monkeypatch, capsys):
    monkeypatch.setenv("GEAROTONS_MOTOR_BACKEND", "auto")
    monkeypatch.setattr(motors, "find_spec", lambda name: None)
    bus = get_bus()
    assert isinstance(bus, MockBus)
    assert bus.simulated_notice == motors.SIMULATED_NOTICE_NO_LIBRARY
    assert "servomotor-mcp[serial]" in bus.simulated_notice
    assert "SIMULATED MOTORS" in capsys.readouterr().err


def test_explicit_mock_says_so(monkeypatch, capsys):
    monkeypatch.setenv("GEAROTONS_MOTOR_BACKEND", "mock")
    bus = get_bus()
    assert isinstance(bus, MockBus)
    assert bus.simulated_notice == motors.SIMULATED_NOTICE_REQUESTED
    assert "SIMULATED MOTORS" in capsys.readouterr().err


def test_auto_with_library_uses_serial_and_has_no_notice(monkeypatch, capsys):
    monkeypatch.setenv("GEAROTONS_MOTOR_BACKEND", "auto")
    monkeypatch.setattr(motors, "find_spec", lambda name: object())
    bus = get_bus()
    assert isinstance(bus, SerialBus)
    assert bus.simulated_notice is None
    assert capsys.readouterr().err == ""


def test_list_serial_ports_carries_the_notice_on_the_simulator(monkeypatch):
    monkeypatch.setenv("GEAROTONS_MOTOR_BACKEND", "mock")
    from servomotor_mcp import server
    importlib.reload(server)
    out = server.list_serial_ports()
    assert out.get("notice", "").startswith("SIMULATED MOTORS")
    res = server.connect(port="MOCK0")
    assert res.get("notice", "").startswith("SIMULATED MOTORS")
