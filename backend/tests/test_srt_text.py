from __future__ import annotations

from app.srt_text import srt_to_plain_text, write_plain_text_from_srt


def test_srt_to_plain_text_strips_sequence_and_timing_rows():
    assert (
        srt_to_plain_text(
            "1\n"
            "00:00:00,000 --> 00:00:01,000\n"
            "[SPEAKER_00] hello world\n\n"
            "2\n"
            "00:00:01.000 --> 00:00:02.500 align:start position:0%\n"
            "second line\n"
        )
        == "[SPEAKER_00] hello world\n\nsecond line"
    )


def test_write_plain_text_from_srt_writes_adjacent_txt(tmp_path):
    srt_path = tmp_path / "result.srt"
    srt_path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nplain text\n",
        encoding="utf-8",
    )

    txt_path = write_plain_text_from_srt(srt_path)

    assert txt_path == tmp_path / "result.txt"
    assert txt_path.read_text(encoding="utf-8") == "plain text\n"
