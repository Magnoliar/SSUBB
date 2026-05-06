"""Coordinator API 集成测试

测试 HTTP API 端点的功能正确性。
使用 FastAPI TestClient，不需要实际启动服务器。
"""

import pytest
from shared.constants import TaskStatus


# ──────────────────────────────────────────────────────────────
# 系统状态
# ──────────────────────────────────────────────────────────────

class TestSystemStatus:
    def test_status_endpoint(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert "version" in data
        assert data["coordinator_online"] is True

    def test_health_endpoint(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert "score" in data
        assert "checks" in data
        assert isinstance(data["checks"], dict)


# ──────────────────────────────────────────────────────────────
# 任务 CRUD
# ──────────────────────────────────────────────────────────────

class TestTaskCRUD:
    def test_create_task(self, client):
        r = client.post("/api/task", json={
            "media_path": "/media/movies/Test.Movie.2024.mkv",
            "media_title": "Test Movie",
            "media_type": "movie",
            "target_lang": "zh",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["media_path"] == "/media/movies/Test.Movie.2024.mkv"
        assert data["status"] == TaskStatus.PENDING
        assert "id" in data

    def test_create_task_minimal(self, client):
        r = client.post("/api/task", json={"media_path": "/test.mkv"})
        assert r.status_code == 200
        assert r.json()["status"] == TaskStatus.PENDING

    def test_get_task(self, client):
        # 创建
        create_r = client.post("/api/task", json={"media_path": "/get_test.mkv"})
        task_id = create_r.json()["id"]

        # 查询
        r = client.get(f"/api/task/{task_id}")
        assert r.status_code == 200
        assert r.json()["id"] == task_id

    def test_get_nonexistent_task(self, client):
        r = client.get("/api/task/nonexistent_id")
        assert r.status_code == 404

    def test_list_tasks(self, client):
        # 创建几个任务
        for i in range(3):
            client.post("/api/task", json={"media_path": f"/list_test_{i}.mkv"})

        r = client.get("/api/tasks")
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "tasks" in data
        assert data["total"] >= 3

    def test_list_tasks_with_status_filter(self, client):
        r = client.get("/api/tasks", params={"status": TaskStatus.PENDING})
        assert r.status_code == 200
        for task in r.json()["tasks"]:
            assert task["status"] == TaskStatus.PENDING

    def test_list_tasks_pagination(self, client):
        r = client.get("/api/tasks", params={"limit": 2, "offset": 0})
        assert r.status_code == 200
        data = r.json()
        assert len(data["tasks"]) <= 2


# ──────────────────────────────────────────────────────────────
# 任务操作
# ──────────────────────────────────────────────────────────────

class TestTaskOperations:
    def test_update_priority(self, client):
        # 创建任务
        create_r = client.post("/api/task", json={"media_path": "/priority_test.mkv"})
        task_id = create_r.json()["id"]

        # 后台任务可能已改变状态，先检查
        task_r = client.get(f"/api/task/{task_id}")
        if task_r.json()["status"] != TaskStatus.PENDING:
            pytest.skip("Task already processed by background task")

        # 修改优先级
        r = client.post(f"/api/task/{task_id}/priority", json={"priority": 1})
        assert r.status_code == 200
        assert r.json()["success"] is True

        # 验证
        task_r = client.get(f"/api/task/{task_id}")
        assert task_r.json()["priority"] == 1

    def test_update_priority_invalid_range(self, client):
        create_r = client.post("/api/task", json={"media_path": "/priority_bad.mkv"})
        task_id = create_r.json()["id"]

        r = client.post(f"/api/task/{task_id}/priority", json={"priority": 0})
        assert r.status_code == 400

        r = client.post(f"/api/task/{task_id}/priority", json={"priority": 6})
        assert r.status_code == 400

    def test_retry_nonexistent_task(self, client):
        r = client.post("/api/task/nonexistent/retry")
        assert r.status_code == 404


# ──────────────────────────────────────────────────────────────
# 批量操作
# ──────────────────────────────────────────────────────────────

class TestBatchOperations:
    def test_batch_cancel(self, client):
        # 创建几个 pending 任务
        ids = []
        for i in range(3):
            r = client.post("/api/task", json={"media_path": f"/cancel_batch_{i}.mkv"})
            ids.append(r.json()["id"])

        # 批量取消
        r = client.post("/api/tasks/batch/cancel", json={"task_ids": ids})
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_batch_cancel_empty(self, client):
        r = client.post("/api/tasks/batch/cancel", json={"task_ids": []})
        assert r.status_code == 400

    def test_batch_delete_empty(self, client):
        r = client.post("/api/tasks/batch/delete", json={"task_ids": []})
        assert r.status_code == 400

    def test_batch_retry_empty(self, client):
        r = client.post("/api/tasks/batch/retry", json={"task_ids": []})
        assert r.status_code == 400


# ──────────────────────────────────────────────────────────────
# 字幕管理
# ──────────────────────────────────────────────────────────────

class TestSubtitleAPI:
    def test_get_subtitle_not_found(self, client):
        create_r = client.post("/api/task", json={"media_path": "/sub_test.mkv"})
        task_id = create_r.json()["id"]

        r = client.get(f"/api/task/{task_id}/subtitle")
        # 任务未完成，字幕不可用
        assert r.status_code in (400, 404)

    def test_get_annotations_not_found(self, client):
        create_r = client.post("/api/task", json={"media_path": "/ann_test.mkv"})
        task_id = create_r.json()["id"]

        r = client.get(f"/api/task/{task_id}/annotations")
        assert r.status_code == 404


# ──────────────────────────────────────────────────────────────
# 统计
# ──────────────────────────────────────────────────────────────

class TestStatistics:
    def test_get_statistics(self, client):
        r = client.get("/api/statistics")
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "completed" in data
        assert "failed" in data
        assert "success_rate" in data

    def test_get_worker_statistics(self, client):
        r = client.get("/api/statistics/workers")
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────────────────────

class TestConfigAPI:
    def test_get_config(self, client):
        r = client.get("/api/config")
        assert r.status_code == 200
        data = r.json()
        assert "host" in data
        assert "port" in data

    def test_config_masks_tokens(self, client):
        r = client.get("/api/config")
        data = r.json()
        # 安全字段应被脱敏（如果配置了 token）
        security = data.get("security", {})
        if security.get("api_token"):
            assert security["api_token"] == "***"


# ──────────────────────────────────────────────────────────────
# Webhook
# ──────────────────────────────────────────────────────────────

class TestWebhook:
    def test_webhook_missing_path(self, client):
        r = client.post("/api/webhook", json={})
        assert r.status_code == 400

    def test_webhook_create_task(self, client):
        r = client.post("/api/webhook", json={
            "media_path": "/webhook/test.mkv",
            "media_title": "Webhook Test",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "task_id" in data.get("data", {})


# ──────────────────────────────────────────────────────────────
# 错误处理
# ──────────────────────────────────────────────────────────────

class TestErrorHandling:
    def test_create_task_missing_path(self, client):
        r = client.post("/api/task", json={})
        assert r.status_code == 422  # Pydantic validation error

    def test_task_detail_not_found(self, client):
        r = client.get("/api/task/nonexistent/detail")
        assert r.status_code == 404

    def test_monitor_scans(self, client):
        r = client.get("/api/monitor/scans")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
