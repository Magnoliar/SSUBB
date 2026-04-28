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
            force_mode=req.force,
            callback_url=req.callback_url,
            status=TaskStatus.PENDING,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        conn = self._get_conn()
        conn.execute(
            """INSERT INTO tasks (id, media_path, media_title, media_type, season,
               episode, tmdb_id, source_lang, target_lang, status, force_mode,
               callback_url, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task.id, task.media_path, task.media_title, task.media_type,
             task.season, task.episode, task.tmdb_id, task.source_lang,
             task.target_lang, task.status, int(task.force_mode),
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
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
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
