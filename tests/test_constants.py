"""SSUBB 共享常量测试"""

import pytest
from shared import constants
from shared.constants import (
    VERSION,
    TaskStatus,
    ErrorCode,
    STAGE_TIMEOUTS,
    VIDEO_EXTENSIONS,
    AUDIO_EXTENSIONS,
    SUBTITLE_EXTENSIONS,
    LANGUAGE_MAP,
    ZH_SUBTITLE_TAGS,
)


class TestVersion:
    def test_version_format(self):
        parts = VERSION.split(".")
        assert len(parts) >= 2
        assert all(p.isdigit() for p in parts)

    def test_version_accessible(self):
        assert VERSION == "1.2.1"


class TestTaskStatus:
    def test_all_statuses_unique(self):
        assert len(TaskStatus.ALL) == len(set(TaskStatus.ALL))

    def test_active_subset_of_all(self):
        assert set(TaskStatus.ACTIVE) <= set(TaskStatus.ALL)

    def test_terminal_subset_of_all(self):
        assert set(TaskStatus.TERMINAL) <= set(TaskStatus.ALL)

    def test_coordinator_stages_subset(self):
        assert set(TaskStatus.COORDINATOR_STAGES) <= set(TaskStatus.ALL)

    def test_worker_stages_subset(self):
        assert set(TaskStatus.WORKER_STAGES) <= set(TaskStatus.ALL)

    def test_active_terminal_disjoint(self):
        assert set(TaskStatus.ACTIVE).isdisjoint(set(TaskStatus.TERMINAL))

    def test_pending_in_active(self):
        assert TaskStatus.PENDING in TaskStatus.ACTIVE

    def test_completed_in_terminal(self):
        assert TaskStatus.COMPLETED in TaskStatus.TERMINAL

    def test_failed_in_terminal(self):
        assert TaskStatus.FAILED in TaskStatus.TERMINAL

    def test_annotating_exists(self):
        assert TaskStatus.ANNOTATING == "annotating"
        assert TaskStatus.ANNOTATING in TaskStatus.ACTIVE
        assert TaskStatus.ANNOTATING in TaskStatus.WORKER_STAGES


class TestErrorCode:
    def test_retryable_subset(self):
        all_codes = {v for k, v in vars(ErrorCode).items() if k.isupper() and isinstance(v, str)}
        assert ErrorCode.RETRYABLE <= all_codes

    def test_retryable_network(self):
        assert ErrorCode.NETWORK_ERROR in ErrorCode.RETRYABLE

    def test_non_retryable_config(self):
        assert ErrorCode.CONFIG_ERROR not in ErrorCode.RETRYABLE

    def test_non_retryable_model(self):
        assert ErrorCode.MODEL_ERROR not in ErrorCode.RETRYABLE


class TestStageTimeouts:
    def test_default_timeout_exists(self):
        assert "_default" in STAGE_TIMEOUTS
        assert STAGE_TIMEOUTS["_default"] > 0

    def test_all_active_stages_have_timeout(self):
        for status in TaskStatus.ACTIVE:
            if status in (TaskStatus.PENDING, TaskStatus.SUBTITLE_CHECKING, TaskStatus.EXTRACTED):
                continue
            assert status in STAGE_TIMEOUTS or "_default" in STAGE_TIMEOUTS

    def test_timeout_values_positive(self):
        for key, val in STAGE_TIMEOUTS.items():
            assert val > 0, f"Timeout for {key} must be positive"


class TestFileExtensions:
    def test_video_extensions_non_empty(self):
        assert len(VIDEO_EXTENSIONS) > 0

    def test_common_video_formats(self):
        for ext in [".mp4", ".mkv", ".avi", ".mov"]:
            assert ext in VIDEO_EXTENSIONS

    def test_extensions_start_with_dot(self):
        for ext in VIDEO_EXTENSIONS:
            assert ext.startswith(".")
        for ext in AUDIO_EXTENSIONS:
            assert ext.startswith(".")
        for ext in SUBTITLE_EXTENSIONS:
            assert ext.startswith(".")

    def test_no_overlap_video_audio(self):
        assert VIDEO_EXTENSIONS.isdisjoint(AUDIO_EXTENSIONS)


class TestLanguageMap:
    def test_chinese_present(self):
        assert "zh" in LANGUAGE_MAP

    def test_english_present(self):
        assert "en" in LANGUAGE_MAP

    def test_auto_present(self):
        assert "auto" in LANGUAGE_MAP


class TestZhSubtitleTags:
    def test_common_tags(self):
        for tag in ["zh", "chi", "chs", "cht", "chinese"]:
            assert tag in ZH_SUBTITLE_TAGS

    def test_all_lowercase(self):
        for tag in ZH_SUBTITLE_TAGS:
            assert tag == tag.lower()
