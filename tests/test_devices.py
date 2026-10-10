import pytest

from mtservice.devices import MT163, MT166, PROFILES, detect


def h(text: str) -> bytes:
    return bytes.fromhex(text)


def test_profiles_are_registered_by_key():
    assert PROFILES == {"mt163": MT163, "mt166": MT166}


@pytest.mark.parametrize(
    "version, profile",
    [
        ("MT163 V3.101", MT163),
        ("MT163 V3.10C", MT163),
        ("MT166 V3.003", MT166),
        ("XYZ", None),
        ("", None),
    ],
)
def test_detect_by_version_string(version, profile):
    assert detect(version) is profile


def test_default_baudrates_follow_vendor_documents():
    assert MT163.baudrate == 38400
    assert MT166.baudrate == 9600


@pytest.mark.parametrize(
    "key, frame",
    [
        ("eject", "02 00 02 31 30 03 02"),
        ("insert_front", "02 00 02 31 31 03 03"),
        ("insert_back", "02 00 02 31 32 03 00"),
        ("retain", "02 00 02 31 33 03 01"),
    ],
)
def test_mt163_mechanics(key, frame):
    assert MT163.command(key).frame() == h(frame)


def test_mt163_timeout_recovery_flag():
    command = MT163.command("timeout_recovery")
    assert command.frame({"enabled": 1}) == h("02 00 03 32 31 01 03 00")
    assert command.frame({"enabled": 0}) == h("02 00 03 32 31 00 03 01")
    assert command.frame() == h("02 00 03 32 31 01 03 00")
    with pytest.raises(ValueError):
        command.frame({"enabled": 2})


def test_card_insertion_waits_longer_than_other_commands():
    assert MT163.command("insert_front").timeout >= 12
    assert MT163.command("insert_back").timeout >= 12
    assert MT163.command("eject").timeout < 12


def test_full_version_only_on_mt163():
    assert MT163.full_version.frame() == h("02 00 02 30 31 03 02")
    assert MT166.full_version is None
    assert MT163.find(0x30, 0x31).key == "full_version"


@pytest.mark.parametrize(
    "key, frame",
    [
        ("to_read", "02 00 02 31 30 03 02"),
        ("to_bezel", "02 00 02 31 31 03 03"),
        ("to_outside", "02 00 02 31 32 03 00"),
        ("collect", "02 00 02 33 30 03 00"),
    ],
)
def test_mt166_mechanics(key, frame):
    assert MT166.command(key).frame() == h(frame)


def test_unknown_command_key():
    with pytest.raises(KeyError):
        MT163.command("to_bezel")


def test_mt163_sensors_follow_card_through_the_slot():
    assert MT163.active_sensors(0x00) == []
    assert MT163.active_sensors(0x10) == ["Датчик Q1"]
    assert MT163.active_sensors(0x30) == ["Датчик Q2", "Датчик Q1"]
    assert MT163.active_sensors(0x70) == ["Датчик Q3", "Датчик Q2", "Датчик Q1"]
    assert MT163.active_sensors(0x02) == ["Ошибка"]


def test_mt166_sensors():
    assert MT166.active_sensors(0x80) == ["Накопитель пуст"]
    assert MT166.active_sensors(0x21) == ["Карта в тракте", "Автосбор"]


def test_sensor_states_cover_every_described_bit():
    states = MT166.sensor_states(0x40)
    assert len(states) == 8
    bezel = next(state for state in states if state.sensor.bit == 6)
    assert bezel.on and bezel.text == "Да"
    assert not states[0].on and states[0].text == "Нет"


def test_status_and_version_frames_are_shared():
    for profile in PROFILES.values():
        assert profile.status.frame() == h("02 00 02 32 30 03 01")
        assert profile.version.frame() == h("02 00 02 30 30 03 03")


def test_find_by_bytes():
    assert MT166.find(0x31, 0x31).key == "to_bezel"
    assert MT166.find(0x32, 0x30).key == "status"
    assert MT166.find(0x77, 0x77) is None
