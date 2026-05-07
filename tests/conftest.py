"""SSUBB 测试共享 fixtures"""

import importlib
import os
import sys
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml


@pytest.fixture
def tmp_db(tmp_path):
    """创建临时 SQLite 数据库"""
    db_path = str(tmp_path / "test.db")
    yield db_path


@pytest.fixture
def task_store(tmp_db):
    """创建 TaskStore 实例"""
    from coordinator.task_store import TaskStore
    return TaskStore(tmp_db)


@pytest.fixture
def sample_task_create():
    """示例 TaskCreate 请求"""
    from shared.models import TaskCreate
    return TaskCreate(
        media_path="/media/movies/The.Matrix.1999.mkv",
        media_title="The Matrix",
        media_type="movie",
        source_lang="en",
        target_lang="zh",
        priority=3,
    )


@pytest.fixture
def sample_task_config():
    """示例 TaskConfig"""
    from shared.models import TaskConfig
    return TaskConfig(
        source_lang="en",
        target_lang="zh",
        whisper_model="large-v3-turbo",
        annotation="auto",
        annotation_quality_threshold=75,
        glossary={"Neo": "尼奥", "Trinity": "崔妮蒂"},
    )


@pytest.fixture
def sample_srt():
    """示例 SRT 字幕文本"""
    return """\
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


# ──────────────────────────────────────────────────────────────
# Coordinator API 集成测试 fixtures
# ──────────────────────────────────────────────────────────────

TEST_API_TOKEN = "test-api-token-for-ci"
TEST_WORKER_TOKEN = "test-worker-token-for-ci"


@pytest.fixture(scope="module")
def coord_config(tmp_path_factory):
    """创建临时 Coordinator 配置"""
    tmp = tmp_path_factory.mktemp("coord")
    db_path = str(tmp / "ssubb.db")
    audio_dir = str(tmp / "audio_temp")
    log_dir = str(tmp / "logs")

    cfg = {
        "coordinator": {
            "host": "127.0.0.1",
            "port": 0,
            "db_path": db_path,
            "audio": {"format": "flac", "sample_rate": 16000, "channels": 1, "temp_dir": audio_dir},
            "worker": {"url": "", "heartbeat_interval": 30, "heartbeat_timeout": 300},
            "workers": [{"url": "http://127.0.0.1:9999", "weight": 1, "enabled": True}],
            "emby": {"server": "", "api_key": ""},
            "discovery": {"enabled": False},
            "security": {"api_token": TEST_API_TOKEN, "worker_token": TEST_WORKER_TOKEN},
            "logging": {"level": "DEBUG", "log_dir": log_dir, "max_size_mb": 1, "backup_count": 1},
            "notifications": {"enabled": False},
        }
    }
    cfg_path = tmp / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg), encoding="utf-8")
    return str(cfg_path)


@pytest.fixture(scope="module")
def coord_app(coord_config):
    """加载 Coordinator 应用（仅加载一次）"""
    env_cfg = os.environ.get("SSUBB_CONFIG")
    os.environ["SSUBB_CONFIG"] = coord_config

    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    import coordinator.config
    importlib.reload(coordinator.config)
    import coordinator.main
    importlib.reload(coordinator.main)

    from coordinator.main import app
    yield app

    if env_cfg is not None:
        os.environ["SSUBB_CONFIG"] = env_cfg
    elif "SSUBB_CONFIG" in os.environ:
        del os.environ["SSUBB_CONFIG"]


@pytest.fixture
def mock_registry():
    """Mock WorkerRegistry"""
    registry = MagicMock()
    registry.get_all_statuses.return_value = []
    registry.get_online_workers.return_value = []
    registry.get_performance_stats.return_value = {}
    registry.get_client_by_url.return_value = None
    registry.reload_config = MagicMock()
    registry.start_heartbeat = AsyncMock()
    registry.stop_heartbeat = AsyncMock()
    return registry


@pytest.fixture
def client(coord_app, mock_registry, tmp_path):
    """FastAPI TestClient with auth headers"""
    from fastapi.testclient import TestClient
    from coordinator.main import app
    import coordinator.main as main_mod
    from coordinator.task_manager import TaskManager
    from coordinator.config import load_config

    config = load_config()
    config.db_path = str(tmp_path / "test.db")

    tm = TaskManager(config, mock_registry)
    main_mod.task_manager = tm
    main_mod.SETUP_REQUIRED = False

    with TestClient(app, raise_server_exceptions=False, headers={
        "Authorization": f"Bearer {TEST_API_TOKEN}",
    }) as c:
        yield c
