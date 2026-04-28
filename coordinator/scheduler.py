"""SSUBB Coordinator - 轻量级自动化调度器

在配置的时间窗口内定期扫描媒体库，自动提交缺字幕的任务。
无重型依赖，纯 asyncio 实现。
"""

import asyncio
import logging
from datetime import datetime, time as dtime
from typing import Optional

from shared.models import TaskCreate

logger = logging.getLogger("ssubb.scheduler")


class AutoScheduler:
    """轻量级自动化调度器

    职责:
    - 在配置的时间窗口内 (如 02:00~06:00) 定期扫描媒体库
    - 发现缺字幕的视频后自动创建任务
    - 检测 Worker 空闲状态，避免过载
    - 任务完成后检测"下一集"并预热
    """

    def __init__(self, config, task_manager, scanner):
        """
        Args:
            config: CoordinatorConfig
            task_manager: TaskManager 实例
            scanner: MediaScanner 实例
        """
        self.config = config
        self.auto_cfg = config.automation
        self.task_manager = task_manager
        self.scanner = scanner

        self._task: Optional[asyncio.Task] = None
        self._enabled = self.auto_cfg.enabled
        self._last_scan: Optional[datetime] = None
        self._last_report: Optional[dict] = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value
        logger.info(f"自动化调度器 {'已启用' if value else '已关闭'}")

    def start(self):
        """启动后台调度循环"""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            logger.info(
                f"自动化调度器已启动 "
                f"(窗口: {self.auto_cfg.schedule_start}~{self.auto_cfg.schedule_end}, "
                f"间隔: {self.auto_cfg.scan_interval}分钟, "
                f"{'已启用' if self._enabled else '已关闭'})"
            )

    def stop(self):
        """停止调度"""
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("自动化调度器已停止")

    def get_status(self) -> dict:
        """查询调度器状态"""
        now = datetime.utcnow()
        in_window = self._in_time_window(now)

        return {
            "enabled": self._enabled,
            "in_window": in_window,
            "schedule_start": self.auto_cfg.schedule_start,
            "schedule_end": self.auto_cfg.schedule_end,
            "scan_interval_minutes": self.auto_cfg.scan_interval,
            "scan_paths": self.auto_cfg.scan_paths,
            "last_scan": self._last_scan.isoformat() if self._last_scan else None,
            "last_report": self._last_report,
        }

    async def trigger_scan(self) -> dict:
        """手动触发一次扫描 (不受时间窗口限制)"""
        logger.info("手动触发扫描...")
        return await self._do_scan()

    # =========================================================================
    # 内部逻辑
    # =========================================================================

    async def _loop(self):
        """主调度循环"""
        check_interval = 60  # 每分钟检查一次是否在窗口内
        scan_cooldown = self.auto_cfg.scan_interval * 60  # 扫描间隔 (秒)

        while True:
            try:
                await asyncio.sleep(check_interval)

                if not self._enabled:
                    continue

                now = datetime.utcnow()

                # 检查是否在时间窗口内
                if not self._in_time_window(now):
                    continue

                # 检查距离上次扫描是否过了足够时间
                if self._last_scan:
                    elapsed = (now - self._last_scan).total_seconds()
                    if elapsed < scan_cooldown:
                        continue

                # 执行扫描
                await self._do_scan()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"调度循环异常: {e}")
                await asyncio.sleep(60)

    async def _do_scan(self) -> dict:
        """执行一次扫描并提交任务"""
        if not self.auto_cfg.scan_paths:
            result = {"error": "未配置扫描路径 (automation.scan_paths)"}
            self._last_report = result
            return result

        # 1. Worker 空闲检测
        if self.auto_cfg.require_worker_idle:
            worker_idle = await self._is_worker_idle()
            if not worker_idle:
                result = {
                    "skipped": True,
                    "reason": "Worker 正忙，等待空闲",
                    "time": datetime.utcnow().isoformat(),
                }
                logger.info("扫描延迟: Worker 正忙")
                self._last_report = result
                return result

        # 2. 扫描
        target_lang = self.config.subtitle.target_language
        report = self.scanner.scan(
            scan_paths=self.auto_cfg.scan_paths,
            target_lang=target_lang,
            recursive=self.auto_cfg.scan_recursive,
            recent_days=self.auto_cfg.scan_recent_days,
            max_results=self.auto_cfg.max_tasks_per_scan,
        )

        self._last_scan = datetime.utcnow()

        # 3. 为缺字幕的视频创建任务
        created = 0
        for item in report.items:
            try:
                req = TaskCreate(
                    media_path=item.path,
                    media_title=item.filename,
                    media_type=item.media_type,
                    target_lang=target_lang,
                )
                await self.task_manager.create_task(req)
                created += 1
            except Exception as e:
                logger.warning(f"自动创建任务失败 [{item.filename}]: {e}")

        report.new_tasks_created = created
        logger.info(f"自动扫描完成: 创建 {created} 个新任务")

        result = {
            "total_videos": report.total_videos,
            "missing_subtitle": report.missing_subtitle,
            "already_active": report.already_active,
            "new_tasks_created": created,
            "duration_seconds": report.duration_seconds,
            "time": self._last_scan.isoformat(),
        }
        self._last_report = result
        return result

    async def preheat_next_episode(self, completed_media_path: str, target_lang: str):
        """任务完成后预热下一集

        Args:
            completed_media_path: 刚完成的媒体文件路径
            target_lang: 目标语言
        """
        if not self.auto_cfg.preheat_next_episode:
            return

        next_ep = self.scanner.find_next_episode(completed_media_path)
        if next_ep is None:
            return

        # 检查下一集是否已有字幕
        existing_sub = self.scanner.checker.find_subtitle(next_ep, target_lang)
        if existing_sub:
            logger.debug(f"下一集已有字幕: {next_ep}")
            return

        # 检查是否已有活跃任务
        existing_task = self.scanner.store.find_existing_task(next_ep, target_lang)
        if existing_task:
            logger.debug(f"下一集已有活跃任务: {next_ep}")
            return

        # 创建预热任务
        from pathlib import Path
        req = TaskCreate(
            media_path=next_ep,
            media_title=Path(next_ep).name,
            media_type="tv",
            target_lang=target_lang,
        )

        try:
            task = await self.task_manager.create_task(req)
            logger.info(f"🔥 预热下一集: {Path(next_ep).name} → 任务 {task.id}")
        except Exception as e:
            logger.warning(f"预热下一集失败: {e}")

    # =========================================================================
    # 工具方法
    # =========================================================================

    def _in_time_window(self, now: datetime) -> bool:
        """判断当前时间是否在调度窗口内"""
        try:
            start = self._parse_time(self.auto_cfg.schedule_start)
            end = self._parse_time(self.auto_cfg.schedule_end)
            current = now.time()

            if start <= end:
                # 普通窗口: 02:00 ~ 06:00
                return start <= current <= end
            else:
                # 跨午夜窗口: 22:00 ~ 06:00
                return current >= start or current <= end
        except Exception:
            return False

    @staticmethod
    def _parse_time(time_str: str) -> dtime:
        """解析 HH:MM 格式的时间"""
        parts = time_str.strip().split(":")
        return dtime(int(parts[0]), int(parts[1]))

    async def _is_worker_idle(self) -> bool:
        """检测 Worker 是否空闲"""
        if not self.task_manager.worker:
            return False
        try:
            status = await self.task_manager.worker.get_status()
            if status is None:
                return False
            return status.queue_length == 0 and status.current_task_id is None
        except Exception:
            return False
