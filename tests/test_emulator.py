from mtservice.devices import MT163, MT166
from mtservice.emulator import Emulator
from mtservice.protocol import FrameReader, OK, decode


def send(device: Emulator, frame: bytes):
    device.write(frame)
    frames = FrameReader().feed(device.read(0.5))
    assert len(frames) == 1
    return decode(frames[0])


def run(device: Emulator, key: str, **values):
    return send(device, device.profile.command(key).frame(values)).status


def status(device: Emulator) -> int:
    return send(device, device.profile.status.frame()).status


def test_emulator_reports_current_firmware_versions():
    assert send(Emulator(MT163), MT163.version.frame()).data == b"MT163 V3.10C"
    assert send(Emulator(MT166), MT166.version.frame()).data == b"MT166 V3.003"
    assert send(Emulator(MT163), MT163.full_version.frame()).data == b"MT163 V3.10C\x00"


def test_mt163_card_cycle():
    device = Emulator(MT163)
    assert status(device) == 0x00
    assert run(device, "eject") == 0x4E
    assert run(device, "insert_front") == OK
    assert status(device) & 0x01
    assert run(device, "eject") == OK
    assert status(device) == 0x10
    assert run(device, "insert_back") == OK
    assert run(device, "retain") == OK
    assert status(device) == 0x00
    assert device.state.retained == 1


def test_mt166_dispense_and_collect():
    device = Emulator(MT166)
    device.state.hopper = 6
    assert run(device, "to_read") == OK
    assert status(device) & 0x20
    assert run(device, "to_bezel") == OK
    assert status(device) & 0x40
    assert run(device, "collect") == OK
    assert device.state.collected == 1
    assert status(device) & 0x10
    assert run(device, "to_outside") == OK
    assert device.state.hopper == 4


def test_mt166_empty_hopper():
    device = Emulator(MT166)
    device.state.hopper = 0
    assert status(device) & 0x80
    assert run(device, "to_read") == 0x4E


def test_unknown_command_gets_nak():
    full_version = bytes.fromhex("02 00 02 30 31 03 02")
    mt163, mt166 = Emulator(MT163), Emulator(MT166)
    mt163.write(bytes.fromhex("02 00 02 77 77 03 03"))
    assert mt163.read(0.5) == b"\x15"
    mt166.write(full_version)
    assert mt166.read(0.5) == b"\x15"


def test_garbage_gets_no_answer():
    device = Emulator(MT163)
    device.write(b"\x55\xAA")
    assert device.read(0.05) == b""


def test_discard_input_drops_pending_reply():
    device = Emulator(MT163)
    device.write(MT163.status.frame())
    device.discard_input()
    assert device.read(0.05) == b""
