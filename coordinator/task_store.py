"""SSUBB Coordinator - SQLite 任务持久化

使用 SQLite 存储任务状态，支持 Coordinator 重启后恢复。
"""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from shared.constants import TaskStatus
from shared.models import TaskConfig, TaskCreate, TaskInfo


class TaskStore:
    """SQLite 任务存储"""

    def __init__(self, db_path: str = "./data/ssubb.db"):
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()
        self._migrate_db()

    def _get_conn(self) -> sqlite3.Connection:
        """每个线程独立的连接"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id           TEXT PRIMARY KEY,
                media_path   TEXT NOT NULL,
                media_title  TEXT,
                media_type   TEXT DEFAULT 'unknown',
                season       INTEGER,
                episode      INTEGER,
                tmdb_id      INTEGER,
                audio_path   TEXT,
                source_lang  TEXT DEFAULT 'auto',
                target_lang  TEXT DEFAULT 'zh',
                status       TEXT DEFAULT 'pending',
                priority     INTEGER DEFAULT 3,
                force_mode   INTEGER DEFAULT 0,
                skip_reason  TEXT,
                callback_url TEXT,
                worker_id    TEXT,
                config_json  TEXT,
                result_json  TEXT,
                error_msg    TEXT,
                error_code   TEXT,
                failed_stage TEXT,
                stage_times_json TEXT,
                retry_count  INTEGER DEFAULT 0,
                progress     INTEGER DEFAULT 0,
                created_at   TEXT,
                updated_at   TEXT,
                completed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_media ON tasks(media_path, target_lang);

            CREATE TABLE IF NOT EXISTS task_subtitles (
                task_id      TEXT PRIMARY KEY,
                srt_content  TEXT,
                original_srt TEXT,
                edited_at    TEXT,
                edit_count   INTEGER DEFAULT 0,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );

            CREATE TABLE IF NOT EXISTS scan_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_time       TEXT NOT NULL,
                total_videos    INTEGER DEFAULT 0,
                missing_subtitle INTEGER DEFAULT 0,
                already_active  INTEGER DEFAULT 0,
                new_tasks_created INTEGER DEFAULT 0,
                duration_seconds REAL DEFAULT 0
            );
        """)
        conn.commit()

    def _migrate_db(self):
        """向后兼容：为旧数据库增加新列"""
        conn = self._get_conn()
        existing_columns = set()
        for row in conn.execute("PRAGMA table_info(tasks)").fetchall():
            existing_columns.add(row["name"])

        new_columns = {
            "error_code": "TEXT",
            "failed_stage": "TEXT",
            "stage_times_json": "TEXT",
            "callback_url": "TEXT",
            "priority": "INTEGER DEFAULT 3",
        }

        for col_name, col_type in new_columns.items():
            if col_name not in existing_columns:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_type}")

        conn.commit()

    # =========================================================================
    # CRUD
    # =========================================================================

    def create_task(self, req: TaskCreate, task_id: Optional[str] = None) -> TaskInfo:
        """创建新任务"""
        from shared.models import _gen_id
        
        now = datetime.utcnow().isoformat()
        task = TaskInfo(
            id=task_id or _gen_id(),
            media_path=req.media_path,
            media_title=req.media_title,
            media_type=req.media_type,
            season=req.season,
            episode=req.episode,
            tmdb_id=req.tmdb_id,
            source_lang=req.source_lang,
            target_lang=req.target_lang,
            priority=req.priority,
            force_mode=req.force,
            callback_url=req.callback_url,
            status=TaskStatus.PENDING,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        conn = self._get_conn()
        conn.execute(
            """INSERT INTO tasks (id, media_path, media_title, media_type, season,
               episode, tmdb_id, source_lang, target_lang, status, priority, force_mode,
               callback_url, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task.id, task.media_path, task.media_title, task.media_type,
             task.season, task.episode, task.tmdb_id, task.source_lang,
             task.target_lang, task.status, task.priority, int(task.force_mode),
             task.callback_url, now, now)
        )
        conn.commit()
        return task

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """查询单个任务"""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def get_tasks(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskInfo]:
        """查询任务列表"""
        conn = self._get_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY priority ASC, created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY priority ASC, created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def count_tasks(self, status: Optional[str] = None) -> int:
        """统计任务总数"""
        conn = self._get_conn()
        if status:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM tasks WHERE status = ?", (status,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as cnt FROM tasks").fetchone()
        return row["cnt"] if row else 0

    def get_pending_tasks(self, limit: int = 10) -> list[TaskInfo]:
        """获取待处理任务"""
        return self.get_tasks(status=TaskStatus.PENDING, limit=limit)

    def update_status(
        self,
        task_id: str,
        status: str,
        progress: int = 0,
        error_msg: Optional[str] = None,
        error_code: Optional[str] = None,
        failed_stage: Optional[str] = None,
        **extra_fields,
    ):
        """更新任务状态"""
        now = datetime.utcnow().isoformat()
        sets = ["status = ?", "progress = ?", "updated_at = ?"]
        vals = [status, progress, now]

        if error_msg is not None:
            sets.append("error_msg = ?")
            vals.append(error_msg)

        if error_code is not None:
            sets.append("error_code = ?")
            vals.append(error_code)

        if failed_stage is not None:
            sets.append("failed_stage = ?")
            vals.append(failed_stage)

        if status == TaskStatus.COMPLETED:
            sets.append("completed_at = ?")
            vals.append(now)

        for key, val in extra_fields.items():
            sets.append(f"{key} = ?")
            vals.append(val)

        vals.append(task_id)
        conn = self._get_conn()
        conn.execute(
            f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", vals
        )
        conn.commit()

    def update_audio_path(self, task_id: str, audio_path: str):
        self._update_field(task_id, "audio_path", audio_path)

    def update_worker(self, task_id: str, worker_id: str):
        self._update_field(task_id, "worker_id", worker_id)

    def update_config(self, task_id: str, config: TaskConfig):
        self._update_field(task_id, "config_json", config.model_dump_json())

    def update_result(self, task_id: str, result_json: str):
        self._update_field(task_id, "result_json", result_json)

    def update_stage_time(self, task_id: str, stage: str, duration: float):
        """记录某个阶段的耗时"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT stage_times_json FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()

        stage_times = {}
        if row and row["stage_times_json"]:
            try:
                stage_times = json.loads(row["stage_times_json"])
            except (json.JSONDecodeError, TypeError):
                pass

        stage_times[stage] = round(duration, 2)
        self._update_field(task_id, "stage_times_json", json.dumps(stage_times))

    def update_result_summary(self, task_id: str, summary: dict):
        """写入结果摘要 (存入 result_json)"""
        self._update_field(task_id, "result_json", json.dumps(summary))

    def reset_for_retry(self, task_id: str):
        """重置任务状态以便重试"""
        conn = self._get_conn()
        now = datetime.utcnow().isoformat()
        conn.execute(
            """UPDATE tasks SET
               status = ?, progress = 0, error_msg = NULL, error_code = NULL,
               failed_stage = NULL, retry_count = retry_count + 1, updated_at = ?
               WHERE id = ?""",
            (TaskStatus.PENDING, now, task_id)
        )
        conn.commit()

    def increment_retry(self, task_id: str):
        conn = self._get_conn()
        conn.execute(
            "UPDATE tasks SET retry_count = retry_count + 1, updated_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), task_id)
        )
        conn.commit()

    def count_by_status(self) -> dict[str, int]:
        """按状态统计任务数量"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
        ).fetchall()
        return {row["status"]: row["cnt"] for row in rows}

    def get_statistics(self, days: int = 30) -> dict:
        """获取统计数据 (最近 N 天)"""
        conn = self._get_conn()
        from datetime import timedelta
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()

        # 总数和成功率
        total_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM tasks WHERE created_at >= ?", (since,)
        ).fetchone()
        total = total_row["cnt"] if total_row else 0

        completed_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM tasks WHERE status = ? AND created_at >= ?",
            (TaskStatus.COMPLETED, since),
        ).fetchone()
        completed = completed_row["cnt"] if completed_row else 0

        failed_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM tasks WHERE status = ? AND created_at >= ?",
            (TaskStatus.FAILED, since),
        ).fetchone()
        failed = failed_row["cnt"] if failed_row else 0

        # 平均耗时 (已完成任务)
        avg_row = conn.execute(
            """SELECT AVG(
                CAST(julianday(completed_at) - julianday(created_at) AS REAL) * 86400
            ) as avg_sec FROM tasks
            WHERE status = ? AND completed_at IS NOT NULL AND created_at >= ?""",
            (TaskStatus.COMPLETED, since),
        ).fetchone()
        avg_duration = round(avg_row["avg_sec"] or 0, 1) if avg_row else 0

        # 按状态分组
        status_rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM tasks WHERE created_at >= ? GROUP BY status",
            (since,),
        ).fetchall()
        by_status = {row["status"]: row["cnt"] for row in status_rows}

        # 按天分组 (最近 7 天)
        day_rows = conn.execute(
            """SELECT DATE(created_at) as day, COUNT(*) as cnt FROM tasks
               WHERE created_at >= DATE('now', '-7 days') GROUP BY DATE(created_at) ORDER BY day"""
        ).fetchall()
        by_day = [{"date": row["day"], "count": row["cnt"]} for row in day_rows]

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "success_rate": round(completed / total * 100, 1) if total > 0 else 0,
            "avg_duration_sec": avg_duration,
            "by_status": by_status,
            "by_day": by_day,
            "days": days,
        }

    def get_worker_statistics(self) -> dict:
        """获取各 Worker 的统计数据"""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT worker_id,
                COUNT(*) as total,
                SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) as failed
               FROM tasks WHERE worker_id IS NOT NULL GROUP BY worker_id""",
            (TaskStatus.COMPLETED, TaskStatus.FAILED),
        ).fetchall()
        result = {}
        for row in rows:
            wid = row["worker_id"]
            total = row["total"]
            completed = row["completed"]
            result[wid] = {
                "total": total,
                "completed": completed,
                "failed": row["failed"],
                "success_rate": round(completed / total * 100, 1) if total > 0 else 0,
            }
        return result

    def update_priority(self, task_id: str, priority: int):
        """更新任务优先级"""
        self._update_field(task_id, "priority", priority)

    # =========================================================================
    # 字幕存储
    # =========================================================================

    def save_subtitle(self, task_id: str, srt_content: str, original_srt: str = ""):
        """保存任务的字幕内容（首次写入或覆盖）"""
        conn = self._get_conn()
        now = datetime.utcnow().isoformat()
        conn.execute(
            """INSERT INTO task_subtitles (task_id, srt_content, original_srt, edited_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(task_id) DO UPDATE SET
                 srt_content = excluded.srt_content,
                 original_srt = COALESCE(NULLIF(excluded.original_srt, ''), task_subtitles.original_srt),
                 edited_at = excluded.edited_at""",
            (task_id, srt_content, original_srt, now),
        )
        conn.commit()

    def get_subtitle(self, task_id: str) -> Optional[dict]:
        """获取任务的字幕内容"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM task_subtitles WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row:
            return dict(row)
        return None

    def update_subtitle_content(self, task_id: str, srt_content: str) -> bool:
        """手动编辑字幕内容"""
        conn = self._get_conn()
        now = datetime.utcnow().isoformat()
        cursor = conn.execute(
            """UPDATE task_subtitles
               SET srt_content = ?, edited_at = ?, edit_count = edit_count + 1
               WHERE task_id = ?""",
            (srt_content, now, task_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    # =========================================================================
    # 扫描历史
    # =========================================================================

    def save_scan_report(self, report: dict):
        """保存扫描报告"""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO scan_history
               (scan_time, total_videos, missing_subtitle, already_active, new_tasks_created, duration_seconds)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                report.get("scan_time", datetime.utcnow().isoformat()),
                report.get("total_videos", 0),
                report.get("missing_subtitle", 0),
                report.get("already_active", 0),
                report.get("new_tasks_created", 0),
                report.get("duration_seconds", 0),
            ),
        )
        conn.commit()

    def get_scan_history(self, limit: int = 10) -> list[dict]:
        """获取最近 N 次扫描记录"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM scan_history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_active_tasks_with_worker(self) -> list[TaskInfo]:
        """获取所有已分配 Worker 的活跃任务"""
        conn = self._get_conn()
        stages = list(TaskStatus.WORKER_STAGES)
        placeholders = ",".join("?" for _ in stages)
        rows = conn.execute(
            f"SELECT * FROM tasks WHERE status IN ({placeholders}) AND worker_id IS NOT NULL",
            stages
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_tasks_by_ids(self, task_ids: list[str]) -> list[TaskInfo]:
        """按 ID 列表批量查询任务"""
        if not task_ids:
            return []
        conn = self._get_conn()
        placeholders = ",".join("?" for _ in task_ids)
        rows = conn.execute(
            f"SELECT * FROM tasks WHERE id IN ({placeholders})", task_ids
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def batch_update_status(
        self,
        task_ids: list[str],
        status: str,
        error_msg: Optional[str] = None,
    ) -> int:
        """批量更新任务状态，返回受影响行数"""
        if not task_ids:
            return 0
        conn = self._get_conn()
        now = datetime.utcnow().isoformat()
        placeholders = ",".join("?" for _ in task_ids)
        if error_msg:
            conn.execute(
                f"UPDATE tasks SET status = ?, error_msg = ?, updated_at = ? WHERE id IN ({placeholders})",
                [status, error_msg, now] + task_ids,
            )
        else:
            conn.execute(
                f"UPDATE tasks SET status = ?, updated_at = ? WHERE id IN ({placeholders})",
                [status, now] + task_ids,
            )
        conn.commit()
        return conn.total_changes

    def batch_delete(self, task_ids: list[str]) -> int:
        """批量删除任务，返回受影响行数"""
        if not task_ids:
            return 0
        conn = self._get_conn()
        placeholders = ",".join("?" for _ in task_ids)
        conn.execute(
            f"DELETE FROM tasks WHERE id IN ({placeholders})", task_ids
        )
        conn.commit()
        return conn.total_changes

    def find_existing_task(self, media_path: str, target_lang: str) -> Optional[TaskInfo]:
        """查找相同媒体+语言的活跃任务 (去重)"""
        conn = self._get_conn()
        placeholders = ",".join("?" for _ in TaskStatus.ACTIVE)
        row = conn.execute(
            f"""SELECT * FROM tasks 
                WHERE media_path = ? AND target_lang = ? AND status IN ({placeholders})
                ORDER BY created_at DESC LIMIT 1""",
            (media_path, target_lang, *TaskStatus.ACTIVE)
        ).fetchone()
        if row:
            return self._row_to_task(row)
        return None

    def find_timed_out_tasks(self, stage_timeouts: dict) -> list[TaskInfo]:
        """查找超时的活跃任务"""
        conn = self._get_conn()
        now = datetime.utcnow()
        timed_out = []

        for status in TaskStatus.ACTIVE:
            if status == TaskStatus.PENDING:
                continue  # pending 不算超时
            timeout_seconds = stage_timeouts.get(status, stage_timeouts.get("_default", 1800))
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ?",
                (status,)
            ).fetchall()
            for row in rows:
                task = self._row_to_task(row)
                if task.updated_at:
                    elapsed = (now - task.updated_at).total_seconds()
                    if elapsed > timeout_seconds:
                        timed_out.append(task)

        return timed_out

    # =========================================================================
    # Internal
    # =========================================================================

    def _update_field(self, task_id: str, field: str, value):
        conn = self._get_conn()
        conn.execute(
            f"UPDATE tasks SET {field} = ?, updated_at = ? WHERE id = ?",
            (value, datetime.utcnow().isoformat(), task_id)
        )
        conn.commit()

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> TaskInfo:
        d = dict(row)
        d["force_mode"] = bool(d.get("force_mode", 0))
        
        # 解析 config_json
        config_json = d.pop("config_json", None)
        if config_json:
            d["config"] = TaskConfig(**json.loads(config_json))
        else:
            d.pop("config_json", None)
        
        # 解析 stage_times_json
        stage_times_json = d.pop("stage_times_json", None)
        if stage_times_json:
            try:
                d["stage_times"] = json.loads(stage_times_json)
            except (json.JSONDecodeError, TypeError):
                d["stage_times"] = {}
        else:
            d["stage_times"] = {}

        # 解析 result_json 为 result_summary
        result_json = d.pop("result_json", None)
        if result_json:
            try:
                d["result_summary"] = json.loads(result_json)
            except (json.JSONDecodeError, TypeError):
                d["result_summary"] = None
        
        # 转换时间字符串
        for tf in ("created_at", "updated_at", "completed_at"):
            v = d.get(tf)
            if v and isinstance(v, str):
                try:
                    d[tf] = datetime.fromisoformat(v)
                except (ValueError, TypeError):
                    d[tf] = None
        
        return TaskInfo(**d)
