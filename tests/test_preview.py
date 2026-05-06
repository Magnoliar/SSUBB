"""SSUBB SRT 解析测试"""

import pytest
from scripts.preview import parse_srt, compute_stats


SAMPLE_SRT = """\
1
00:00:01,000 --> 00:00:03,500
Hello, welcome to the show.

2
00:00:04,000 --> 00:00:06,200
This is a test subtitle.

3
00:00:07,500 --> 00:00:10,000
Goodbye and see you next time.
"""

BILINGUAL_SRT = """\
1
00:00:01,000 --> 00:00:03,000
Hello world
你好世界

2
00:00:04,000 --> 00:00:06,000
Good morning
早上好
"""

EMPTY_SRT = ""

SINGLE_ENTRY_SRT = """\
1
00:00:05,000 --> 00:00:10,000
Only one line.
"""


class TestParseSrt:
    def test_parse_count(self):
        entries = parse_srt(SAMPLE_SRT)
        assert len(entries) == 3

    def test_parse_index(self):
        entries = parse_srt(SAMPLE_SRT)
        assert entries[0]["index"] == 1
        assert entries[1]["index"] == 2
        assert entries[2]["index"] == 3

    def test_parse_timestamps(self):
        entries = parse_srt(SAMPLE_SRT)
        assert entries[0]["start"] == "00:00:01,000"
        assert entries[0]["end"] == "00:00:03,500"

    def test_parse_text(self):
        entries = parse_srt(SAMPLE_SRT)
        assert "Hello" in entries[0]["text"]
        assert "test subtitle" in entries[1]["text"]
        assert "Goodbye" in entries[2]["text"]

    def test_parse_start_sec(self):
        entries = parse_srt(SAMPLE_SRT)
        assert entries[0]["start_sec"] == 1.0
        assert entries[1]["start_sec"] == 4.0

    def test_parse_end_sec(self):
        entries = parse_srt(SAMPLE_SRT)
        assert entries[0]["end_sec"] == 3.5
        assert entries[2]["end_sec"] == 10.0

    def test_parse_empty(self):
        entries = parse_srt(EMPTY_SRT)
        assert entries == []

    def test_parse_single(self):
        entries = parse_srt(SINGLE_ENTRY_SRT)
        assert len(entries) == 1
        assert entries[0]["text"] == "Only one line."

    def test_parse_bilingual(self):
        entries = parse_srt(BILINGUAL_SRT)
        assert len(entries) == 2
        assert "\n" in entries[0]["text"]

    def test_bom_handling(self):
        bom_srt = "﻿" + SAMPLE_SRT
        entries = parse_srt(bom_srt)
        assert len(entries) == 3


class TestComputeStats:
    def test_count(self):
        entries = parse_srt(SAMPLE_SRT)
        stats = compute_stats(entries, 1.0)
        assert stats["count"] == 3

    def test_empty_stats(self):
        stats = compute_stats([], 0)
        assert stats["count"] == 0

    def test_duration(self):
        entries = parse_srt(SAMPLE_SRT)
        stats = compute_stats(entries, 1.0)
        assert stats["duration_sec"] == 10.0

    def test_density(self):
        entries = parse_srt(SAMPLE_SRT)
        stats = compute_stats(entries, 1.0)
        # 3 条 / (10s / 60) = 18 条/分钟
        assert stats["density"] == pytest.approx(18.0, abs=0.1)

    def test_has_cjk_false(self):
        entries = parse_srt(SAMPLE_SRT)
        stats = compute_stats(entries, 1.0)
        assert stats["has_cjk"] is False

    def test_has_cjk_true(self):
        entries = parse_srt(BILINGUAL_SRT)
        stats = compute_stats(entries, 1.0)
        assert stats["has_cjk"] is True

    def test_bilingual_detection(self):
        entries = parse_srt(BILINGUAL_SRT)
        stats = compute_stats(entries, 1.0)
        assert stats["bilingual_count"] == 2

    def test_avg_len(self):
        entries = parse_srt(SAMPLE_SRT)
        stats = compute_stats(entries, 1.0)
        assert stats["avg_len"] > 0

    def test_file_size(self):
        entries = parse_srt(SAMPLE_SRT)
        stats = compute_stats(entries, 5.5)
        assert stats["file_size_kb"] == 5.5
