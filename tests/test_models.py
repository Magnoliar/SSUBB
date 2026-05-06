"""SSUBB Pydantic 数据模型测试"""

import pytest
from pydantic import ValidationError

from shared.models import (
    LLMProviderConfig,
    LLMHealthStatus,
    TaskConfig,
    TaskCreate,
    TaskInfo,
    WorkerTaskRequest,
    WorkerProgressUpdate,
    WorkerTaskResult,
    WorkerHeartbeat,
    WorkerStatus,
    APIResponse,
    TaskListResponse,
    SystemStatus,
    ScanHistoryEntry,
    _gen_id,
)


class TestGenId:
    def test_length(self):
        assert len(_gen_id()) == 12

    def test_hex(self):
        id_ = _gen_id()
        assert all(c in "0123456789abcdef" for c in id_)

    def test_uniqueness(self):
        ids = {_gen_id() for _ in range(100)}
        assert len(ids) == 100


class TestLLMProviderConfig:
    def test_defaults(self):
        cfg = LLMProviderConfig(api_base="https://api.test.com/v1", api_key="sk-xxx", model="gpt-4")
        assert cfg.priority == 1
        assert cfg.enabled is True
        assert cfg.label == ""

    def test_custom(self):
        cfg = LLMProviderConfig(
            api_base="https://api.test.com/v1",
            api_key="sk-xxx",
            model="deepseek-chat",
            priority=2,
            enabled=False,
            label="备用",
        )
        assert cfg.priority == 2
        assert cfg.enabled is False
        assert cfg.label == "备用"

    def test_missing_required(self):
        with pytest.raises(ValidationError):
            LLMProviderConfig()


class TestLLMHealthStatus:
    def test_defaults(self):
        s = LLMHealthStatus(provider_label="test", healthy=True)
        assert s.latency_ms == 0
        assert s.last_error == ""

    def test_with_error(self):
        s = LLMHealthStatus(provider_label="test", healthy=False, last_error="Connection refused")
        assert s.healthy is False
        assert "refused" in s.last_error


class TestTaskConfig:
    def test_defaults(self):
        cfg = TaskConfig()
        assert cfg.source_lang == "auto"
        assert cfg.target_lang == "zh"
        assert cfg.whisper_model == "large-v3-turbo"
        assert cfg.annotation == "off"
        assert cfg.terminology_enabled is True
        assert cfg.glossary is None

    def test_with_glossary(self):
        cfg = TaskConfig(glossary={"Neo": "尼奥", "Trinity": "崔妮蒂"})
        assert cfg.glossary["Neo"] == "尼奥"
        assert len(cfg.glossary) == 2

    def test_annotation_modes(self):
        for mode in ("off", "auto", "on"):
            cfg = TaskConfig(annotation=mode)
            assert cfg.annotation == mode

    def test_reflect(self):
        cfg = TaskConfig(need_reflect=True)
        assert cfg.need_reflect is True


class TestTaskCreate:
    def test_required_field(self):
        with pytest.raises(ValidationError):
            TaskCreate()

    def test_minimal(self):
        t = TaskCreate(media_path="/test.mkv")
        assert t.media_path == "/test.mkv"
        assert t.priority == 3
        assert t.annotation == "off"
        assert t.force is False

    def test_full(self):
        t = TaskCreate(
            media_path="/media/movie.mkv",
            media_title="Movie",
            media_type="movie",
            season=1,
            episode=1,
            tmdb_id=12345,
            source_lang="en",
            target_lang="zh",
            audio_track=0,
            annotation="auto",
            force=True,
            priority=1,
            callback_url="https://example.com/callback",
        )
        assert t.priority == 1
        assert t.season == 1
        assert t.force is True

    def test_priority_bounds(self):
        TaskCreate(media_path="/t.mkv", priority=1)
        TaskCreate(media_path="/t.mkv", priority=5)
        with pytest.raises(ValidationError):
            TaskCreate(media_path="/t.mkv", priority=0)
        with pytest.raises(ValidationError):
            TaskCreate(media_path="/t.mkv", priority=6)


class TestTaskInfo:
    def test_defaults(self):
        t = TaskInfo(media_path="/test.mkv")
        assert len(t.id) == 12
        assert t.status == "pending"
        assert t.priority == 3
        assert t.progress == 0
        assert t.retry_count == 0
        assert t.stage_times == {}

    def test_from_attributes(self):
        assert TaskInfo.model_config.get("from_attributes") is True


class TestWorkerTaskRequest:
    def test_defaults(self):
        r = WorkerTaskRequest(task_id="abc123")
        assert r.source_lang == "auto"
        assert r.target_lang == "zh"
        assert r.config is not None


class TestWorkerProgressUpdate:
    def test_valid(self):
        u = WorkerTaskUpdate = WorkerProgressUpdate(task_id="abc", status="transcribing", progress=50)
        assert u.progress == 50

    def test_progress_bounds(self):
        WorkerProgressUpdate(task_id="abc", status="s", progress=0)
        WorkerProgressUpdate(task_id="abc", status="s", progress=100)
        with pytest.raises(ValidationError):
            WorkerProgressUpdate(task_id="abc", status="s", progress=-1)
        with pytest.raises(ValidationError):
            WorkerProgressUpdate(task_id="abc", status="s", progress=101)


class TestWorkerTaskResult:
    def test_minimal(self):
        r = WorkerTaskResult(task_id="abc", status="completed")
        assert r.subtitle_srt is None
        assert r.annotations is None
        assert r.partial_translation is False

    def test_with_annotations(self):
        r = WorkerTaskResult(
            task_id="abc",
            status="completed",
            subtitle_srt="1\n00:00:01,000 --> 00:00:02,000\nHello\n",
            annotations=[{"index": 1, "start": "00:00:01", "end": "00:00:02", "text": "注释"}],
            cultural_density="high",
        )
        assert len(r.annotations) == 1
        assert r.cultural_density == "high"

    def test_partial_translation(self):
        r = WorkerTaskResult(task_id="abc", status="completed", partial_translation=True)
        assert r.partial_translation is True


class TestWorkerHeartbeat:
    def test_defaults(self):
        h = WorkerHeartbeat(worker_id="w1", version="0.12.0")
        assert h.queue_length == 0
        assert h.current_progress == 0
        assert h.gpu_name is None


class TestAPIResponse:
    def test_defaults(self):
        r = APIResponse()
        assert r.success is True
        assert r.message == "OK"

    def test_error(self):
        r = APIResponse(success=False, message="Not found")
        assert r.success is False


class TestSystemStatus:
    def test_defaults(self):
        s = SystemStatus(version="0.12.0")
        assert s.coordinator_online is True
        assert s.workers == []
        assert s.tasks_pending == 0


class TestScanHistoryEntry:
    def test_defaults(self):
        e = ScanHistoryEntry(scan_time="2026-05-05T12:00:00")
        assert e.total_videos == 0
        assert e.new_tasks_created == 0
