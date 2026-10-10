import pytest

from mtservice.protocol import FrameError, FrameReader, bcc, decode, encode, status_text


def h(text: str) -> bytes:
    return bytes.fromhex(text)


@pytest.mark.parametrize(
    "cm, pm, data, frame",
    [
        (0x30, 0x30, b"", "02 00 02 30 30 03 03"),
        (0x32, 0x30, b"", "02 00 02 32 30 03 01"),
        (0x31, 0x33, b"", "02 00 02 31 33 03 01"),
        (0x33, 0x30, b"", "02 00 02 33 30 03 00"),
        (0x32, 0x31, h("01"), "02 00 03 32 31 01 03 00"),
        (0x30, 0x31, b"", "02 00 02 30 31 03 02"),
        (0x35, 0x32, h("05 FF FF FF FF FF FF"), "02 00 09 35 32 05 FF FF FF FF FF FF 03 0A"),
    ],
)
def test_encode_matches_frames_from_vendor_logs(cm, pm, data, frame):
    assert encode(cm, pm, data) == h(frame)


def test_bcc_is_xor_of_all_bytes():
    assert bcc(h("02 00 02 30 30 03")) == 0x03
    assert bcc(b"") == 0


def test_decode_version_reply():
    reply = decode(h("02 00 0F 30 30 59 4D 54 31 36 33 20 56 33 2E 31 30 31 03 21"))
    assert (reply.cm, reply.pm) == (0x30, 0x30)
    assert reply.status == 0x59
    assert reply.data == b"MT163 V3.101"


def test_decode_status_reply():
    reply = decode(h("02 00 03 32 30 70 03 70"))
    assert reply.status == 0x70
    assert reply.data == b""


@pytest.mark.parametrize(
    "frame",
    [
        "02 00 02 30 30 03",
        "03 00 02 30 30 03 03",
        "02 00 02 30 30 03 04",
        "02 00 03 30 30 03 03",
        "02 00 02 30 30 04 04",
    ],
)
def test_decode_rejects_broken_frames(frame):
    with pytest.raises(FrameError):
        decode(h(frame))


def test_reader_assembles_split_frame():
    reader = FrameReader()
    assert reader.feed(h("02 00 03 32")) == []
    assert reader.feed(h("30 10 03 10")) == [h("02 00 03 32 30 10 03 10")]
    assert reader.pending == 0


def test_reader_skips_line_noise_before_frame():
    reader = FrameReader()
    frames = reader.feed(h("78 7F F8 08 0F 7B FF") + h("02 00 03 32 30 00 03 00"))
    assert frames == [h("02 00 03 32 30 00 03 00")]
    assert reader.skipped == 7


def test_reader_resyncs_after_bad_checksum():
    reader = FrameReader()
    frames = reader.feed(h("02 00 03 32 30 00 03 FF") + h("02 00 03 32 30 20 03 20"))
    assert frames == [h("02 00 03 32 30 20 03 20")]
    assert reader.skipped == 8


def test_reader_does_not_wait_for_absurd_length():
    reader = FrameReader()
    frames = reader.feed(h("02 7F F8") + h("02 00 03 31 30 59 03 5A"))
    assert frames == [h("02 00 03 31 30 59 03 5A")]


def test_reader_returns_several_frames_from_one_chunk():
    reader = FrameReader()
    chunk = h("02 00 03 32 30 40 03 40") + h("02 00 03 32 30 20 03 20")
    assert len(reader.feed(chunk)) == 2


def test_status_text():
    assert status_text(0x59) == "успешно"
    assert status_text(0x4E) == "отказ"
    assert status_text(0x45) == "нет карты"
    assert status_text(0x57) == "карта не в рабочей позиции"
    assert status_text(0x12) == "код 0x12"
