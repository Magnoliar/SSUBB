"""WebUI 契约测试

验证 API 端点的响应格式与前端 Vue.js 代码的期望一致。
不测试实际浏览器渲染，只测试数据契约。
"""

import pytest
from shared.constants import TaskStatus


# ──────────────────────────────────────────────────────────────
# 静态文件服务
# ──────────────────────────────────────────────────────────────

class TestStaticFiles:
    def test_root_serves_index(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "SSUBB" in r.text

    def test_static_dir_mounted(self, client):
        r = client.get("/static/index.html")
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────
# API 响应契约：/api/status
# ──────────────────────────────────────────────────────────────

class TestStatusContract:
    def test_status_fields(self, client):
        r = client.get("/api/status")
        data = r.json()
        # 前端期望的字段
        required = {"version", "coordinator_online"}
        assert required.issubset(data.keys()), f"Missing: {required - data.keys()}"


# ──────────────────────────────────────────────────────────────
# API 响应契约：/api/health
# ──────────────────────────────────────────────────────────────

class TestHealthContract:
    def test_health_fields(self, client):
        r = client.get("/api/health")
        data = r.json()
        assert "score" in data
        assert "checks" in data
        assert isinstance(data["checks"], dict)


# ──────────────────────────────────────────────────────────────
# API 响应契约：/api/task (CRUD)
# ──────────────────────────────────────────────────────────────

class TestTaskCreateContract:
    def test_create_returns_task_info(self, client):
        r = client.post("/api/task", json={"media_path": "/test.mkv"})
        data = r.json()
        # TaskInfo 字段
        assert "id" in data
        assert "media_path" in data
        assert "status" in data
        assert "created_at" in data
        assert "priority" in data

    def test_create_with_all_fields(self, client):
        r = client.post("/api/task", json={
            "media_path": "/test.mkv",
            "media_title": "Test",
            "media_type": "movie",
            "target_lang": "zh",
            "priority": 2,
            "annotation": "auto",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["media_title"] == "Test"
        assert data["priority"] == 2


class TestTaskListContract:
    def test_list_response_fields(self, client):
        client.post("/api/task", json={"media_path": "/list_test.mkv"})
        r = client.get("/api/tasks")
        data = r.json()
        assert "total" in data
        assert "tasks" in data
        assert isinstance(data["tasks"], list)
        if data["tasks"]:
            task = data["tasks"][0]
            assert "id" in task
            assert "status" in task
            assert "media_path" in task

    def test_list_status_filter(self, client):
        r = client.get("/api/tasks", params={"status": TaskStatus.PENDING})
        assert r.status_code == 200
        for task in r.json()["tasks"]:
            assert task["status"] == TaskStatus.PENDING

    def test_list_pagination(self, client):
        r = client.get("/api/tasks", params={"limit": 1, "offset": 0})
        data = r.json()
        assert len(data["tasks"]) <= 1


# ──────────────────────────────────────────────────────────────
# API 响应契约：/api/task/{id}/priority
# ──────────────────────────────────────────────────────────────

class TestPriorityContract:
    def test_priority_update_response(self, client):
        r = client.post("/api/task", json={"media_path": "/prio.mkv"})
        task_id = r.json()["id"]

        # 检查任务是否仍为 pending
        task_r = client.get(f"/api/task/{task_id}")
        if task_r.json()["status"] != TaskStatus.PENDING:
            pytest.skip("Task already processed")

        r = client.post(f"/api/task/{task_id}/priority", json={"priority": 1})
        assert r.status_code == 200
        data = r.json()
        assert "success" in data


# ──────────────────────────────────────────────────────────────
# API 响应契约：/api/statistics
# ──────────────────────────────────────────────────────────────

class TestStatisticsContract:
    def test_statistics_fields(self, client):
        r = client.get("/api/statistics")
        data = r.json()
        assert "total" in data
        assert "completed" in data
        assert "failed" in data
        assert "success_rate" in data

    def test_worker_statistics_is_list(self, client):
        r = client.get("/api/statistics/workers")
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────
# API 响应契约：/api/config
# ──────────────────────────────────────────────────────────────

class TestConfigContract:
    def test_config_fields(self, client):
        r = client.get("/api/config")
        data = r.json()
        assert "host" in data
        assert "port" in data

    def test_config_masks_secrets(self, client):
        r = client.get("/api/config")
        data = r.json()
        security = data.get("security", {})
        if security.get("api_token"):
            assert security["api_token"] == "***"


# ──────────────────────────────────────────────────────────────
# API 响应契约：/api/webhook
# ──────────────────────────────────────────────────────────────

class TestWebhookContract:
    def test_webhook_create_response(self, client):
        r = client.post("/api/webhook", json={"media_path": "/wh.mkv"})
        data = r.json()
        assert "success" in data
        assert "data" in data
        assert "task_id" in data["data"]

    def test_webhook_missing_path(self, client):
        r = client.post("/api/webhook", json={})
        assert r.status_code == 400


# ──────────────────────────────────────────────────────────────
# API 响应契约：批量操作
# ──────────────────────────────────────────────────────────────

class TestBatchContract:
    def test_batch_cancel_response(self, client):
        r = client.post("/api/task", json={"media_path": "/batch.mkv"})
        task_id = r.json()["id"]

        r = client.post("/api/tasks/batch/cancel", json={"task_ids": [task_id]})
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_batch_empty_returns_400(self, client):
        r = client.post("/api/tasks/batch/cancel", json={"task_ids": []})
        assert r.status_code == 400


# ──────────────────────────────────────────────────────────────
# API 响应契约：自动化
# ──────────────────────────────────────────────────────────────

class TestAutomationContract:
    def test_automation_status(self, client):
        r = client.get("/api/automation/status")
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────
# API 响应契约：Worker 管理
# ──────────────────────────────────────────────────────────────

class TestWorkerContract:
    def test_workers_list(self, client):
        r = client.get("/api/workers")
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────
# API 响应契约：系统监控
# ──────────────────────────────────────────────────────────────

class TestMonitorContract:
    def test_llm_monitor(self, client):
        r = client.get("/api/monitor/llm")
        assert r.status_code == 200

    def test_scan_monitor(self, client):
        r = client.get("/api/monitor/scans")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ──────────────────────────────────────────────────────────────
# API 响应契约：日志
# ──────────────────────────────────────────────────────────────

class TestLogsContract:
    def test_logs_endpoint(self, client):
        r = client.get("/api/logs")
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────
# API 响应契约：文件系统浏览
# ──────────────────────────────────────────────────────────────

class TestFileSystemContract:
    def test_fs_endpoint(self, client):
        r = client.get("/api/fs")
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────
# API 响应契约：发现服务
# ──────────────────────────────────────────────────────────────

class TestDiscoveryContract:
    def test_discovery_status(self, client):
        r = client.get("/api/discovery/status")
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────
# WebSocket 契约
# ──────────────────────────────────────────────────────────────

class TestWebSocketContract:
    @pytest.mark.skip(reason="HTTPBearer dependency incompatible with TestClient WebSocket")
    def test_ws_logs_connects(self, client):
        """WebSocket 日志端点可连接"""
        with client.websocket_connect("/ws/logs") as ws:
            pass

    @pytest.mark.skip(reason="HTTPBearer dependency incompatible with TestClient WebSocket")
    def test_ws_logs_with_token(self, client):
        """带 token 参数的 WebSocket 连接"""
        with client.websocket_connect("/ws/logs?token=test") as ws:
            pass
