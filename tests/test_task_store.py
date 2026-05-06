"""SSUBB TaskStore 测试"""

import pytest
from shared.constants import TaskStatus
from shared.models import TaskCreate, TaskConfig


class TestTaskStoreInit:
    def test_creates_db_file(self, task_store, tmp_db):
        from pathlib import Path
        assert Path(tmp_db).exists()

    def test_creates_data_dir(self, tmp_path):
        from pathlib import Path
        from coordinator.task_store import TaskStore
        db = str(tmp_path / "sub" / "dir" / "test.db")
        TaskStore(db)
        assert Path(db).parent.exists()


class TestCreateTask:
    def test_create_returns_task_info(self, task_store, sample_task_create):
        task = task_store.create_task(sample_task_create)
        assert task is not None
        assert task.id is not None
        assert len(task.id) > 0
        assert task.media_path == sample_task_create.media_path

    def test_create_returns_unique_ids(self, task_store):
        from shared.models import TaskCreate
        ids = set()
        for i in range(10):
            t = TaskCreate(media_path=f"/test/{i}.mkv")
            task = task_store.create_task(t)
            ids.add(task.id)
        assert len(ids) == 10

    def test_create_with_config(self, task_store):
        from shared.models import TaskCreate
        t = TaskCreate(
            media_path="/test.mkv",
            annotation="auto",
            audio_track=2,
            priority=1,
        )
        task = task_store.create_task(t)
        assert task.priority == 1

    def test_duplicate_media_path(self, task_store, sample_task_create):
        t1 = task_store.create_task(sample_task_create)
        t2 = task_store.create_task(sample_task_create)
        assert t1.id != t2.id


class TestGetTask:
    def test_get_existing(self, task_store, sample_task_create):
        created = task_store.create_task(sample_task_create)
        task = task_store.get_task(created.id)
        assert task is not None
        assert task.media_path == sample_task_create.media_path
        assert task.status == TaskStatus.PENDING

    def test_get_nonexistent(self, task_store):
        task = task_store.get_task("nonexistent_id")
        assert task is None

    def test_fields_populated(self, task_store, sample_task_create):
        created = task_store.create_task(sample_task_create)
        task = task_store.get_task(created.id)
        assert task.media_title == "The Matrix"
        assert task.media_type == "movie"
        assert task.source_lang == "en"
        assert task.target_lang == "zh"
        assert task.created_at is not None


class TestUpdateStatus:
    def test_update_status(self, task_store, sample_task_create):
        created = task_store.create_task(sample_task_create)
        task_store.update_status(created.id, TaskStatus.EXTRACTING, progress=30)
        task = task_store.get_task(created.id)
        assert task.status == TaskStatus.EXTRACTING
        assert task.progress == 30

    def test_update_with_error(self, task_store, sample_task_create):
        created = task_store.create_task(sample_task_create)
        task_store.update_status(
            created.id,
            TaskStatus.FAILED,
            error_msg="Network timeout",
            error_code="network_error",
            failed_stage="uploading",
        )
        task = task_store.get_task(created.id)
        assert task.status == TaskStatus.FAILED
        assert "timeout" in task.error_msg
        assert task.error_code == "network_error"
        assert task.failed_stage == "uploading"

    def test_completed_at_set(self, task_store, sample_task_create):
        created = task_store.create_task(sample_task_create)
        task_store.update_status(created.id, TaskStatus.COMPLETED)
        task = task_store.get_task(created.id)
        assert task.completed_at is not None

    def test_progress_bounds(self, task_store, sample_task_create):
        created = task_store.create_task(sample_task_create)
        task_store.update_status(created.id, TaskStatus.TRANSCRIBING, progress=0)
        assert task_store.get_task(created.id).progress == 0
        task_store.update_status(created.id, TaskStatus.TRANSCRIBING, progress=100)
        assert task_store.get_task(created.id).progress == 100


class TestGetTasks:
    def test_list_empty(self, task_store):
        tasks = task_store.get_tasks()
        assert tasks == []

    def test_list_returns_all(self, task_store):
        from shared.models import TaskCreate
        for i in range(5):
            task_store.create_task(TaskCreate(media_path=f"/test/{i}.mkv"))
        tasks = task_store.get_tasks()
        assert len(tasks) == 5

    def test_list_with_status_filter(self, task_store, sample_task_create):
        created = task_store.create_task(sample_task_create)
        task_store.update_status(created.id, TaskStatus.COMPLETED)
        task_store.create_task(TaskCreate(media_path="/other.mkv"))

        tasks = task_store.get_tasks(status=TaskStatus.COMPLETED)
        assert len(tasks) == 1
        assert tasks[0].status == TaskStatus.COMPLETED

    def test_list_pagination(self, task_store):
        from shared.models import TaskCreate
        for i in range(20):
            task_store.create_task(TaskCreate(media_path=f"/test/{i}.mkv"))
        tasks = task_store.get_tasks(limit=5, offset=0)
        assert len(tasks) == 5


class TestCountTasks:
    def test_count_empty(self, task_store):
        assert task_store.count_tasks() == 0

    def test_count_all(self, task_store):
        from shared.models import TaskCreate
        for i in range(3):
            task_store.create_task(TaskCreate(media_path=f"/test/{i}.mkv"))
        assert task_store.count_tasks() == 3

    def test_count_by_status(self, task_store, sample_task_create):
        created = task_store.create_task(sample_task_create)
        task_store.update_status(created.id, TaskStatus.COMPLETED)
        task_store.create_task(TaskCreate(media_path="/other.mkv"))
        assert task_store.count_tasks(status=TaskStatus.COMPLETED) == 1
        assert task_store.count_tasks(status=TaskStatus.PENDING) == 1


class TestSubtitleStorage:
    def test_save_and_get(self, task_store, sample_task_create, sample_srt):
        created = task_store.create_task(sample_task_create)
        task_store.save_subtitle(created.id, sample_srt, None)
        sub = task_store.get_subtitle(created.id)
        assert sub is not None
        assert "Hello" in sub["srt_content"]

    def test_save_with_original(self, task_store, sample_task_create, sample_srt):
        created = task_store.create_task(sample_task_create)
        original = "1\n00:00:01,000 --> 00:00:02,000\nOriginal\n"
        task_store.save_subtitle(created.id, sample_srt, original)
        sub = task_store.get_subtitle(created.id)
        assert sub is not None
        assert sub["original_srt"] is not None

    def test_get_nonexistent_subtitle(self, task_store):
        sub = task_store.get_subtitle("nonexistent")
        assert sub is None


class TestAnnotations:
    def test_save_and_get_annotations(self, task_store, sample_task_create, sample_srt):
        created = task_store.create_task(sample_task_create)
        task_store.save_subtitle(created.id, sample_srt, None)
        task_store.save_annotations(created.id, "annotation content here")
        ann = task_store.get_annotations(created.id)
        assert ann == "annotation content here"

    def test_get_nonexistent_annotations(self, task_store):
        ann = task_store.get_annotations("nonexistent")
        assert ann is None


class TestStageTimes:
    def test_update_stage_time(self, task_store, sample_task_create):
        created = task_store.create_task(sample_task_create)
        task_store.update_stage_time(created.id, "extracting", 12.5)
        task_store.update_stage_time(created.id, "transcribing", 45.3)
        task = task_store.get_task(created.id)
        assert task.stage_times["extracting"] == 12.5
        assert task.stage_times["transcribing"] == 45.3


class TestRetryCount:
    def test_increment_retry(self, task_store, sample_task_create):
        created = task_store.create_task(sample_task_create)
        task_store.increment_retry(created.id)
        task_store.increment_retry(created.id)
        task = task_store.get_task(created.id)
        assert task.retry_count == 2


class TestResetForRetry:
    def test_reset(self, task_store, sample_task_create):
        created = task_store.create_task(sample_task_create)
        task_store.update_status(
            created.id, TaskStatus.FAILED,
            error_msg="fail", error_code="llm_error", failed_stage="translating",
        )
        task_store.reset_for_retry(created.id)
        task = task_store.get_task(created.id)
        assert task.status == TaskStatus.PENDING
        assert task.error_msg is None
        assert task.retry_count == 1


class TestDeleteTask:
    def test_delete_nonexistent(self, task_store):
        # 没有 delete_task 方法，但可以用 batch_delete
        affected = task_store.batch_delete(["nonexistent"])
        assert affected == 0


class TestBatchOperations:
    def test_batch_update_status(self, task_store):
        from shared.models import TaskCreate
        tasks = []
        for i in range(5):
            tasks.append(task_store.create_task(TaskCreate(media_path=f"/test/{i}.mkv")))
        ids = [t.id for t in tasks]
        affected = task_store.batch_update_status(ids[:3], TaskStatus.CANCELLED)
        assert affected >= 3
        for tid in ids[:3]:
            assert task_store.get_task(tid).status == TaskStatus.CANCELLED
        for tid in ids[3:]:
            assert task_store.get_task(tid).status == TaskStatus.PENDING

    def test_batch_delete(self, task_store):
        from shared.models import TaskCreate
        tasks = []
        for i in range(5):
            tasks.append(task_store.create_task(TaskCreate(media_path=f"/test/{i}.mkv")))
        ids = [t.id for t in tasks]
        affected = task_store.batch_delete(ids[:2])
        assert affected >= 2
        assert task_store.get_task(ids[0]) is None
        assert task_store.get_task(ids[3]) is not None


class TestFindExistingTask:
    def test_find_active(self, task_store, sample_task_create):
        created = task_store.create_task(sample_task_create)
        found = task_store.find_existing_task(sample_task_create.media_path, "zh")
        assert found is not None
        assert found.id == created.id

    def test_find_not_found(self, task_store):
        found = task_store.find_existing_task("/nonexistent.mkv", "zh")
        assert found is None

    def test_find_skips_completed(self, task_store, sample_task_create):
        created = task_store.create_task(sample_task_create)
        task_store.update_status(created.id, TaskStatus.COMPLETED)
        found = task_store.find_existing_task(sample_task_create.media_path, "zh")
        assert found is None


class TestScanHistory:
    def test_save_and_get(self, task_store):
        report = {
            "scan_time": "2026-05-05T12:00:00",
            "total_videos": 100,
            "missing_subtitle": 20,
            "already_active": 5,
            "new_tasks_created": 15,
            "duration_seconds": 45.2,
        }
        task_store.save_scan_report(report)
        history = task_store.get_scan_history(limit=1)
        assert len(history) == 1
        assert history[0]["total_videos"] == 100
        assert history[0]["new_tasks_created"] == 15


class TestStatistics:
    def test_get_statistics_empty(self, task_store):
        stats = task_store.get_statistics()
        assert stats["total"] == 0
        assert stats["success_rate"] == 0

    def test_get_statistics(self, task_store):
        from shared.models import TaskCreate
        for i in range(5):
            t = task_store.create_task(TaskCreate(media_path=f"/test/{i}.mkv"))
            if i < 3:
                task_store.update_status(t.id, TaskStatus.COMPLETED)
            else:
                task_store.update_status(t.id, TaskStatus.FAILED)
        stats = task_store.get_statistics()
        assert stats["total"] == 5
        assert stats["completed"] == 3
        assert stats["failed"] == 2

    def test_worker_statistics(self, task_store):
        from shared.models import TaskCreate
        t = task_store.create_task(TaskCreate(media_path="/test.mkv"))
        task_store.update_status(t.id, TaskStatus.COMPLETED)
        task_store.update_worker(t.id, "worker-1")
        ws = task_store.get_worker_statistics()
        assert "worker-1" in ws


class TestMigration:
    def test_migration_idempotent(self, tmp_path):
        """多次迁移不应出错"""
        from coordinator.task_store import TaskStore
        db = str(tmp_path / "test.db")
        store1 = TaskStore(db)
        store2 = TaskStore(db)
        store3 = TaskStore(db)
        t = TaskCreate(media_path="/test.mkv")
        task = store3.create_task(t)
        assert store3.get_task(task.id) is not None
