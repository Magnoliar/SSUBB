"""SSUBB 配置加载与迁移测试"""

import os
import pytest
import yaml
from pathlib import Path


class TestCoordinatorConfig:
    def test_default_config(self):
        from coordinator.config import CoordinatorConfig
        cfg = CoordinatorConfig()
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8787
        assert cfg.db_path == "./data/ssubb.db"

    def test_workers_empty_by_default(self):
        from coordinator.config import CoordinatorConfig
        cfg = CoordinatorConfig()
        assert cfg.workers == []

    def test_security_defaults(self):
        from coordinator.config import CoordinatorConfig
        cfg = CoordinatorConfig()
        assert cfg.security.api_token == ""
        assert cfg.security.worker_token == ""

    def test_annotation_defaults(self):
        from coordinator.config import CoordinatorConfig
        cfg = CoordinatorConfig()
        assert cfg.annotation.mode == "off"
        assert cfg.annotation.quality_threshold == 75

    def test_discovery_defaults(self):
        from coordinator.config import CoordinatorConfig
        cfg = CoordinatorConfig()
        assert cfg.discovery.enabled is True
        assert cfg.discovery.port == 8789


class TestConfigLoading:
    def test_load_from_yaml(self, tmp_path):
        from coordinator.config import load_config
        cfg_data = {
            "coordinator": {
                "host": "127.0.0.1",
                "port": 9999,
                "db_path": str(tmp_path / "test.db"),
                "workers": [{"url": "http://10.0.0.1:8788", "weight": 2}],
            }
        }
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump(cfg_data), encoding="utf-8")

        cfg = load_config(str(cfg_path))
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 9999
        assert len(cfg.workers) == 1
        assert cfg.workers[0].url == "http://10.0.0.1:8788"
        assert cfg.workers[0].weight == 2

    def test_load_nonexistent_file(self, tmp_path):
        from coordinator.config import load_config
        cfg = load_config(str(tmp_path / "nonexistent.yaml"))
        # 应该返回默认配置
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8787

    def test_backward_compat_migration(self, tmp_path):
        """旧格式 worker.url 自动迁移到 workers 列表"""
        from coordinator.config import load_config
        cfg_data = {
            "coordinator": {
                "worker": {"url": "http://192.168.1.50:8788"},
            }
        }
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump(cfg_data), encoding="utf-8")

        cfg = load_config(str(cfg_path))
        assert len(cfg.workers) == 1
        assert cfg.workers[0].url == "http://192.168.1.50:8788"

    def test_env_override_db_path(self, tmp_path, monkeypatch):
        from coordinator.config import load_config
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump({"coordinator": {}}), encoding="utf-8")

        monkeypatch.setenv("SSUBB_DB_PATH", str(tmp_path / "custom.db"))
        cfg = load_config(str(cfg_path))
        assert cfg.db_path == str(tmp_path / "custom.db")

    def test_env_override_worker_url(self, tmp_path, monkeypatch):
        from coordinator.config import load_config
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump({"coordinator": {}}), encoding="utf-8")

        monkeypatch.setenv("SSUBB_WORKER_URL", "http://10.0.0.99:8788")
        cfg = load_config(str(cfg_path))
        assert cfg.worker.url == "http://10.0.0.99:8788"

    def test_env_override_security_tokens(self, tmp_path, monkeypatch):
        from coordinator.config import load_config
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump({"coordinator": {}}), encoding="utf-8")

        monkeypatch.setenv("SSUBB_API_TOKEN", "test-api-token")
        monkeypatch.setenv("SSUBB_WORKER_TOKEN", "test-worker-token")
        cfg = load_config(str(cfg_path))
        assert cfg.security.api_token == "test-api-token"
        assert cfg.security.worker_token == "test-worker-token"

    def test_env_worker_urls_multi(self, tmp_path, monkeypatch):
        """SSUBB_WORKER_URLS 逗号分隔多 Worker"""
        from coordinator.config import load_config
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump({"coordinator": {}}), encoding="utf-8")

        monkeypatch.setenv("SSUBB_WORKER_URLS", "http://10.0.0.1:8788,http://10.0.0.2:8788")
        cfg = load_config(str(cfg_path))
        assert len(cfg.workers) == 2


class TestConfigSave:
    def test_save_and_reload(self, tmp_path):
        from coordinator.config import load_config, save_config
        cfg_path = str(tmp_path / "config.yaml")

        cfg_data = {
            "host": "192.168.1.1",
            "port": 5555,
            "workers": [{"url": "http://test:8788"}],
        }
        save_config(cfg_data, cfg_path)

        # 重新加载
        cfg = load_config(cfg_path)
        assert cfg.host == "192.168.1.1"
        assert cfg.port == 5555
        assert len(cfg.workers) == 1


class TestWorkerConfig:
    def test_worker_default_config(self):
        from worker.config import WorkerConfig
        cfg = WorkerConfig()
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8788

    def test_worker_transcribe_defaults(self):
        from worker.config import WorkerConfig
        cfg = WorkerConfig()
        assert cfg.transcribe.model == "large-v3-turbo"
        assert cfg.transcribe.device == "cuda"

    def test_worker_translate_defaults(self):
        from worker.config import WorkerConfig
        cfg = WorkerConfig()
        assert cfg.translate.target_language == "zh"
        assert cfg.translate.batch_size == 10
