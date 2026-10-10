import struct

import pytest

from mtservice import bootloader
from mtservice.bootloader import FlashCancelled, FlashError, Flasher, blocks, check_image, image_version
from mtservice.emulator import BootloaderEmulator


def make_image(size=1000, version=b"MT163 V3.10C"):
    head = struct.pack("<II", 0x20001170, 0x080022E5)
    body = bytes(i * 7 & 0xFF for i in range(size - len(head) - len(version)))
    return head + body + version


def test_blocks_are_numbered_padded_and_summed():
    image = make_image(600)
    result = blocks(image)
    assert len(result) == 3
    assert all(len(block) == 259 for block in result)
    assert [int.from_bytes(block[:2], "big") for block in result] == [0, 1, 2]
    assert result[0][2:258] == image[:256]
    assert result[2][2 + 88:258] == b"\xff" * 168
    assert all(sum(block[2:258]) & 0xFF == block[258] for block in result)


def test_image_version():
    assert image_version(make_image()) == "MT163 V3.10C"
    assert image_version(make_image(version=b"MT166 V3.003")) == "MT166 V3.003"
    assert image_version(b"\x00" * 64) is None


@pytest.mark.parametrize(
    "image",
    [
        b"\x00" * 4,
        bytes.fromhex("0c94f002") + b"\xff" * 996,
        struct.pack("<II", 0x20001170, 0x08000101) + b"\x00" * 992,
        struct.pack("<II", 0x20001170, 0x080022E5) + b"\x00" * 0xE000,
    ],
    ids=["short", "avr", "wrong-base", "too-big"],
)
def test_check_image_rejects_foreign_images(image):
    with pytest.raises(FlashError):
        check_image(image)


def test_full_flash_on_emulator():
    image = make_image(1000)
    device = BootloaderEmulator(reset_after=0.05)
    stages, progress = [], []
    flasher = Flasher(device, image, on_stage=stages.append, on_progress=lambda d, t: progress.append((d, t)))
    flasher.run()
    assert device.finished
    assert bytes(device.image[:len(image)]) == image
    assert set(device.image[len(image):]) == {0xFF}
    assert progress[-1] == (4, 4)
    assert stages[0].startswith("Нажмите кнопку сброса")
    assert stages[-1] == "Прошивка записана"


def test_device_that_never_enters_bootloader():
    flasher = Flasher(BootloaderEmulator(), make_image(), hello_timeout=0.2)
    with pytest.raises(FlashError, match="не вошло в загрузчик"):
        flasher.run()


def test_rejected_block_stops_flashing():
    device = BootloaderEmulator(reset_after=0.01)
    device.broken_block = 2
    flasher = Flasher(device, make_image(1000), block_timeout=0.2)
    with pytest.raises(FlashError, match="блок 3 из 4"):
        flasher.run()
    assert not device.finished


def test_restart_during_flashing_is_detected():
    device = BootloaderEmulator(reset_after=0.01)

    def progress(done, total):
        if done == 1:
            device.press_reset()

    flasher = Flasher(device, make_image(1000), on_progress=progress, block_timeout=0.5)
    with pytest.raises(FlashError, match="перезагрузилось"):
        flasher.run()


def test_cancel_while_waiting_for_reset():
    flasher = Flasher(BootloaderEmulator(), make_image(), hello_timeout=5)
    flasher.cancel()
    with pytest.raises(FlashCancelled):
        flasher.run()


def test_handshake_constants_match_vendor_flasher():
    assert bootloader.MAGIC.hex(" ") == "37 46 52 83 44 85 62"
    assert bootloader.IDENT == b"MT318%"
    assert bootloader.BAUDRATE == 115200
