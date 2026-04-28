"""SSUBB Coordinator - 媒体库扫描器

扫描指定目录，发现缺少目标语言字幕的视频文件。
用于自动化补字幕场景。
"""

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from shared.constants import VIDEO_EXTENSIONS

logger = logging.getLogger("ssubb.scanner")


@dataclass
class ScanItem:
    """单个扫描结果"""
    path: str
    filename: str
    size_mb: float
    modified_at: datetime
    has_subtitle: bool = False
    has_active_task: bool = False
    media_type: str = "unknown"  # movie / tv


@dataclass
class ScanReport:
    """扫描汇总报告"""
    scan_time: datetime = field(default_factory=datetime.utcnow)
    scanned_dirs: list[str] = field(default_factory=list)
    total_videos: int = 0
    missing_subtitle: int = 0
    already_active: int = 0
    new_tasks_created: int = 0
    items: list[ScanItem] = field(default_factory=list)
    duration_seconds: float = 0.0


class MediaScanner:
    """媒体库扫描器

    扫描指定目录，找出缺少字幕的视频文件，
    结合 SubtitleChecker 和 TaskStore 做去重。
    """

    def __init__(self, subtitle_checker, task_store):
        """
        Args:
            subtitle_checker: SubtitleChecker 实例
            task_store: TaskStore 实例
        """
        self.checker = subtitle_checker
        self.store = task_store

    def scan(
        self,
        scan_paths: list[str],
        target_lang: str = "zh",
        recursive: bool = True,
        recent_days: int = 0,
        max_results: int = 50,
    ) -> ScanReport:
        """扫描媒体目录，返回缺字幕的视频列表

        Args:
            scan_paths: 要扫描的目录列表
            target_lang: 目标字幕语言
            recursive: 是否递归扫描子目录
            recent_days: 只扫描最近 N 天修改的文件 (0=不限)
            max_results: 最多返回的结果数

        Returns:
            ScanReport 扫描报告
        """
        t0 = time.time()
        report = ScanReport(scanned_dirs=list(scan_paths))

        cutoff_time = None
        if recent_days > 0:
            cutoff_time = datetime.utcnow() - timedelta(days=recent_days)

        # 1. 收集所有视频文件
        all_videos: list[ScanItem] = []
        for scan_path in scan_paths:
            p = Path(scan_path)
            if not p.exists() or not p.is_dir():
                logger.warning(f"扫描路径不存在或非目录: {scan_path}")
                continue
            self._collect_videos(p, all_videos, recursive, cutoff_time)

        report.total_videos = len(all_videos)
        logger.info(f"扫描发现 {len(all_videos)} 个视频文件")

        # 2. 检查字幕存在性 + 任务去重
        missing: list[ScanItem] = []
        for item in all_videos:
            # 检查是否已有合格字幕
            existing_sub = self.checker.find_subtitle(item.path, target_lang)
            if existing_sub:
                item.has_subtitle = True
                continue

            # 检查是否已有活跃任务
            existing_task = self.store.find_existing_task(item.path, target_lang)
            if existing_task:
                item.has_active_task = True
                report.already_active += 1
                continue

            # 检查近 24 小时内是否刚完成过
            from shared.constants import TaskStatus
            recent_completed = self.store.get_tasks(status=TaskStatus.COMPLETED, limit=200)
            is_recently_done = any(
                t.media_path == item.path
                and t.target_lang == target_lang
                and t.completed_at
                and (datetime.utcnow() - t.completed_at).total_seconds() < 86400
                for t in recent_completed
            )
            if is_recently_done:
                item.has_subtitle = True  # 视作已有
                continue

            missing.append(item)

        report.missing_subtitle = len(missing)

        # 3. 排序: 最近修改 > 电影 > 电视剧
        missing.sort(key=lambda x: (
            0 if x.media_type == "movie" else 1,
            -x.modified_at.timestamp(),
        ))

        # 4. 截断
        report.items = missing[:max_results]
        report.duration_seconds = round(time.time() - t0, 2)

        logger.info(
            f"扫描完成: {report.total_videos} 个视频, "
            f"{report.missing_subtitle} 个缺字幕, "
            f"{report.already_active} 个已有任务, "
            f"耗时 {report.duration_seconds}s"
        )

        return report

    def find_next_episode(self, completed_media_path: str) -> Optional[str]:
        """查找刚完成任务的"下一集"

        逻辑: 在同目录下找文件名排序上的下一个视频文件。

        Args:
            completed_media_path: 刚完成的视频文件路径

        Returns:
            下一集的路径，若无则返回 None
        """
        completed = Path(completed_media_path)
        parent = completed.parent
        if not parent.is_dir():
            return None

        # 收集同目录下的视频文件并排序
        siblings = sorted(
            f for f in parent.iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        )

        # 找到当前文件的位置
        try:
            idx = siblings.index(completed)
        except ValueError:
            return None

        # 返回下一个
        if idx + 1 < len(siblings):
            return str(siblings[idx + 1])
        return None

    def _collect_videos(
        self,
        directory: Path,
        results: list[ScanItem],
        recursive: bool,
        cutoff_time: Optional[datetime],
    ):
        """递归收集视频文件"""
        try:
            for entry in os.scandir(directory):
                if entry.is_dir() and recursive:
                    # 跳过隐藏目录和常见非媒体目录
                    if entry.name.startswith(".") or entry.name.startswith("@"):
                        continue
                    if entry.name.lower() in {"subtitles", "subs", "extras", "featurettes", "behind the scenes"}:
                        continue
                    self._collect_videos(Path(entry.path), results, recursive, cutoff_time)

                elif entry.is_file():
                    suffix = Path(entry.name).suffix.lower()
                    if suffix not in VIDEO_EXTENSIONS:
                        continue

                    stat = entry.stat()
                    # 跳过极小文件 (< 50MB，可能是预告片/样本)
                    if stat.st_size < 50 * 1024 * 1024:
                        continue

                    modified = datetime.utcfromtimestamp(stat.st_mtime)

                    # 时间过滤
                    if cutoff_time and modified < cutoff_time:
                        continue

                    # 简单的类型推断: 路径中有 Season / S01 等关键词 → TV
                    path_lower = entry.path.lower()
                    media_type = "tv" if any(
                        kw in path_lower
                        for kw in ["season", "/s0", "\\s0", "/s1", "\\s1",
                                   "第", "集", "episode", "/e0", "\\e0"]
                    ) else "movie"

                    results.append(ScanItem(
                        path=entry.path,
                        filename=entry.name,
                        size_mb=round(stat.st_size / (1024 * 1024), 1),
                        modified_at=modified,
                        media_type=media_type,
                    ))

        except PermissionError:
            logger.debug(f"跳过无权限目录: {directory}")
        except Exception as e:
            logger.warning(f"扫描目录异常 {directory}: {e}")
