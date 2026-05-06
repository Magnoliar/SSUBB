"""Worker 组件集成测试

测试 SRT 解析、LLM 客户端初始化、翻译/优化器的非 LLM 部分。
不测试实际的 LLM API 调用（需要网络和 API Key）。
"""

import pytest
from shared.models import LLMProviderConfig, TaskConfig


# ──────────────────────────────────────────────────────────────
# SRTParser
# ──────────────────────────────────────────────────────────────

class TestSRTParser:
    def test_parse_basic(self):
        from worker.srt_parser import SRTParser
        srt = "1\n00:00:01,000 --> 00:00:03,000\nHello world\n"
        segments = SRTParser.parse(srt)
        assert len(segments) == 1
        assert segments[0].index == 1
        assert segments[0].text == "Hello world"
        assert segments[0].start_time == "00:00:01,000"
        assert segments[0].end_time == "00:00:03,000"

    def test_parse_multiple(self):
        from worker.srt_parser import SRTParser
        srt = (
            "1\n00:00:01,000 --> 00:00:03,000\nFirst line\n\n"
            "2\n00:00:04,000 --> 00:00:06,000\nSecond line\n\n"
            "3\n00:00:07,000 --> 00:00:09,000\nThird line\n"
        )
        segments = SRTParser.parse(srt)
        assert len(segments) == 3
        assert segments[1].text == "Second line"
        assert segments[2].index == 3

    def test_parse_dot_separator(self):
        from worker.srt_parser import SRTParser
        srt = "1\n00:00:01.000 --> 00:00:03.000\nDot separated\n"
        segments = SRTParser.parse(srt)
        assert len(segments) == 1
        # 应该统一为逗号
        assert "," in segments[0].start_time

    def test_parse_multiline_text(self):
        from worker.srt_parser import SRTParser
        srt = "1\n00:00:01,000 --> 00:00:05,000\nLine one\nLine two\n"
        segments = SRTParser.parse(srt)
        assert len(segments) == 1
        assert "\n" in segments[0].text

    def test_parse_empty(self):
        from worker.srt_parser import SRTParser
        assert SRTParser.parse("") == []
        assert SRTParser.parse("   ") == []

    def test_reconstruct(self):
        from worker.srt_parser import SRTParser, SubtitleSegment
        segments = [
            SubtitleSegment(1, "00:00:01,000", "00:00:03,000", "Hello"),
            SubtitleSegment(2, "00:00:04,000", "00:00:06,000", "World"),
        ]
        srt = SRTParser.build(segments)
        assert "1\n" in srt
        assert "00:00:01,000 --> 00:00:03,000" in srt
        assert "Hello" in srt
        assert "2\n" in srt

    def test_roundtrip(self):
        from worker.srt_parser import SRTParser
        original = (
            "1\n00:00:01,000 --> 00:00:03,000\nHello\n\n"
            "2\n00:00:04,000 --> 00:00:06,000\nWorld\n"
        )
        segments = SRTParser.parse(original)
        reconstructed = SRTParser.build(segments)
        # 解析重建后应该保持一致
        segments2 = SRTParser.parse(reconstructed)
        assert len(segments2) == len(segments)
        for s1, s2 in zip(segments, segments2):
            assert s1.text == s2.text
            assert s1.start_time == s2.start_time


# ──────────────────────────────────────────────────────────────
# LLMClient 初始化
# ──────────────────────────────────────────────────────────────

class TestLLMClientInit:
    def test_sort_by_priority(self):
        from worker.llm_client import LLMClient
        providers = [
            LLMProviderConfig(api_base="http://a.com/v1", api_key="k", model="m", priority=3, label="low"),
            LLMProviderConfig(api_base="http://b.com/v1", api_key="k", model="m", priority=1, label="high"),
            LLMProviderConfig(api_base="http://c.com/v1", api_key="k", model="m", priority=2, label="mid"),
        ]
        client = LLMClient(providers)
        labels = [p.label for p in client.providers]
        assert labels == ["high", "mid", "low"]

    def test_filter_disabled(self):
        from worker.llm_client import LLMClient
        providers = [
            LLMProviderConfig(api_base="http://a.com/v1", api_key="k", model="m", priority=1, label="active"),
            LLMProviderConfig(api_base="http://b.com/v1", api_key="k", model="m", priority=2, label="disabled", enabled=False),
        ]
        client = LLMClient(providers)
        assert len(client.providers) == 1
        assert client.providers[0].label == "active"

    def test_model_from_highest_priority(self):
        from worker.llm_client import LLMClient
        providers = [
            LLMProviderConfig(api_base="http://a.com/v1", api_key="k", model="gpt-4", priority=2, label="a"),
            LLMProviderConfig(api_base="http://b.com/v1", api_key="k", model="deepseek-chat", priority=1, label="b"),
        ]
        client = LLMClient(providers)
        assert client.model == "deepseek-chat"

    def test_empty_providers(self):
        from worker.llm_client import LLMClient
        client = LLMClient([])
        assert client.providers == []
        assert client.model == ""

    def test_health_snapshot_initialized(self):
        from worker.llm_client import LLMClient
        providers = [
            LLMProviderConfig(api_base="http://a.com/v1", api_key="k", model="m", priority=1, label="test"),
        ]
        client = LLMClient(providers)
        health = client.get_health_snapshot()
        assert len(health) == 1
        assert health[0].provider_label == "test"
        assert health[0].healthy is True


# ──────────────────────────────────────────────────────────────
# SubtitleTranslator 结构测试
# ──────────────────────────────────────────────────────────────

class TestTranslatorStructure:
    def test_init(self):
        from worker.llm_client import LLMClient
        from worker.translator import SubtitleTranslator
        client = LLMClient([])
        translator = SubtitleTranslator(client)
        assert translator.llm is client


# ──────────────────────────────────────────────────────────────
# SubtitleOptimizer 结构测试
# ──────────────────────────────────────────────────────────────

class TestOptimizerStructure:
    def test_init(self):
        from worker.llm_client import LLMClient
        from worker.optimizer import SubtitleOptimizer
        client = LLMClient([])
        optimizer = SubtitleOptimizer(client)
        assert optimizer.llm is client

    def test_build_system_prompt(self):
        from worker.optimizer import _build_system_prompt
        from worker.config import OptimizeConfig
        cfg = OptimizeConfig(max_word_count_cjk=15, max_word_count_english=20)
        prompt = _build_system_prompt(cfg)
        assert "15" in prompt
        assert "20" in prompt


# ──────────────────────────────────────────────────────────────
# Worker Config 加载
# ──────────────────────────────────────────────────────────────

class TestWorkerConfig:
    def test_default_configs(self):
        from worker.config import (
            TranscribeConfig, LLMConfig, TranslateConfig,
            OptimizeConfig, VRAMConfig,
        )
        tc = TranscribeConfig()
        assert tc.model == "large-v3-turbo"
        assert tc.device == "cuda"
        assert tc.vad_filter is True

        lc = LLMConfig()
        assert lc.model == "deepseek-chat"

        trc = TranslateConfig()
        assert trc.target_language == "zh"
        assert trc.thread_num == 5

        oc = OptimizeConfig()
        assert oc.enabled is True
        assert oc.max_word_count_cjk == 12

        vc = VRAMConfig()
        assert vc.clear_on_complete is True

    def test_transcribe_config_custom(self):
        from worker.config import TranscribeConfig
        tc = TranscribeConfig(model="base", device="cpu", compute_type="int8")
        assert tc.model == "base"
        assert tc.device == "cpu"


# ──────────────────────────────────────────────────────────────
# Annotator 结构测试
# ──────────────────────────────────────────────────────────────

class TestAnnotator:
    def test_max_notes_calculation(self):
        from worker.annotator import SubtitleAnnotator
        from worker.llm_client import LLMClient
        ann = SubtitleAnnotator(LLMClient([]))
        # 短视频: 2 条
        assert ann._calculate_max_notes(600) == 2       # 10 min
        # 中等: 5 条
        assert ann._calculate_max_notes(2700) == 5      # 45 min
        # 长片: 8 条
        assert ann._calculate_max_notes(7200) == 8      # 120 min
        # 超长: 10 条
        assert ann._calculate_max_notes(10800) == 10    # 180 min

    def test_time_to_seconds(self):
        from worker.annotator import SubtitleAnnotator
        assert SubtitleAnnotator._time_to_seconds("00:01:30,500") == 90.5
        assert SubtitleAnnotator._time_to_seconds("01:00:00,000") == 3600.0
        assert SubtitleAnnotator._time_to_seconds("00:00:00,000") == 0.0

    def test_process_annotations_valid(self):
        from worker.annotator import SubtitleAnnotator
        from worker.llm_client import LLMClient
        from worker.srt_parser import SubtitleSegment
        ann = SubtitleAnnotator(LLMClient([]))
        segments = [
            SubtitleSegment(1, "00:00:01,000", "00:00:03,000", "Hello"),
            SubtitleSegment(2, "00:00:05,000", "00:00:07,000", "World"),
        ]
        raw = [
            {"index": 1, "text": "这是一条注释"},
            {"index": 2, "text": "另一条注释"},
        ]
        result = ann._process_annotations(raw, segments, 10)
        assert result is not None
        assert len(result) == 2
        assert result[0]["start_time"] == "00:00:01,000"

    def test_process_annotations_empty(self):
        from worker.annotator import SubtitleAnnotator
        from worker.llm_client import LLMClient
        from worker.srt_parser import SubtitleSegment
        ann = SubtitleAnnotator(LLMClient([]))
        result = ann._process_annotations([], [], 10)
        assert result is None

    def test_process_annotations_truncates_long_text(self):
        from worker.annotator import SubtitleAnnotator
        from worker.llm_client import LLMClient
        from worker.srt_parser import SubtitleSegment
        ann = SubtitleAnnotator(LLMClient([]))
        segments = [SubtitleSegment(1, "00:00:01,000", "00:00:03,000", "Hi")]
        raw = [{"index": 1, "text": "这是一条非常非常非常非常非常非常非常非常非常长的注释文本"}]
        result = ann._process_annotations(raw, segments, 10)
        assert result is not None
        assert len(result[0]["text"]) <= 30
