"""自动更新模块

检查 GitHub Releases → 下载 → 备份 → 替换 → 回滚。
"""

import json
import os
import platform
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

from PySide6.QtCore import QObject, QThread, Signal


def _parse_version(v: str) -> tuple:
    """'v1.2.3' 或 '1.2.3' → (1, 2, 3)。"""
    v = v.lstrip("v")
    parts = []
    for p in v.split(".")[:3]:
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _get_platform_suffix() -> str:
    """获取当前平台的 release 文件后缀。"""
    system = platform.system().lower()
    arch = "win64" if system == "windows" else "linux-x64"
    return arch


class UpdateChecker(QObject):
    """后台检查 GitHub Releases 是否有新版本。"""

    update_available = Signal(str, str, str)  # version, url, body
    no_update = Signal()

    _repo = "anthropics/ssubb"

    def __init__(self, parent=None):
        super().__init__(parent)

    def check(self):
        """延迟 3 秒后检查。"""
        from PySide6.QtCore import QTimer
        QTimer.singleShot(3000, self._do_check)

    def _do_check(self):
        try:
            from shared.constants import VERSION
            current = _parse_version(VERSION)
        except Exception:
            return

        try:
            url = f"https://api.github.com/repos/{self._repo}/releases/latest"
            req = Request(url, headers={"Accept": "application/vnd.github.v3+json"})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            tag = data.get("tag_name", "")
            remote = _parse_version(tag)
            if remote > current:
                self.update_available.emit(
                    tag.lstrip("v"),
                    data.get("html_url", ""),
                    data.get("body", "")[:500],
                )
            else:
                self.no_update.emit()

        except (URLError, OSError, json.JSONDecodeError, KeyError):
            self.no_update.emit()


class DownloadWorker(QThread):
    """后台下载更新文件。"""

    progress = Signal(int)          # 0-100
    finished = Signal(str)          # zip 文件路径
    error = Signal(str)             # 错误信息

    def __init__(self, url, dest_path):
        super().__init__()
        self._url = url
        self._dest = dest_path

    def run(self):
        try:
            req = Request(self._url)
            with urlopen(req, timeout=300) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 8192

                with open(self._dest, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            self.progress.emit(int(downloaded * 100 / total))

            self.finished.emit(self._dest)

        except Exception as e:
            self.error.emit(str(e))


def apply_update(zip_path: str, backup: bool = True) -> bool:
    """应用更新：解压 zip 替换当前文件。

    Args:
        zip_path: 下载的 zip 文件路径
        backup: 是否备份当前版本

    Returns:
        True 成功，False 失败（已自动回滚）
    """
    app_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent.parent
    backup_dir = app_dir / "backup"

    try:
        # 1. 备份当前版本
        if backup and backup_dir.exists():
            shutil.rmtree(backup_dir)
        if backup:
            shutil.copytree(app_dir, backup_dir, ignore=shutil.ignore_patterns("backup", "__pycache__", "*.pyc"))

        # 2. 解压更新
        with zipfile.ZipFile(zip_path, "r") as zf:
            # 安全检查：不允许路径穿越
            for name in zf.namelist():
                if ".." in name or name.startswith("/"):
                    raise ValueError(f"Unsafe path in zip: {name}")
            zf.extractall(app_dir)

        return True

    except Exception as e:
        # 3. 回滚
        if backup_dir.exists():
            try:
                # 删除解压的文件
                with zipfile.ZipFile(zip_path, "r") as zf:
                    for name in zf.namelist():
                        target = app_dir / name
                        if target.exists():
                            if target.is_dir():
                                shutil.rmtree(target)
                            else:
                                target.unlink()

                # 恢复备份
                for item in backup_dir.iterdir():
                    dest = app_dir / item.name
                    if dest.exists():
                        if dest.is_dir():
                            shutil.rmtree(dest)
                        else:
                            dest.unlink()
                    if item.is_dir():
                        shutil.copytree(item, dest)
                    else:
                        shutil.copy2(item, dest)

            except Exception:
                pass  # 回滚失败，用户需要手动恢复

        return False


def find_update_asset(release_data: dict) -> str:
    """从 release 数据中找到当前平台的下载 URL。"""
    suffix = _get_platform_suffix()
    assets = release_data.get("assets", [])

    # 优先找 launcher zip
    for asset in assets:
        name = asset.get("name", "")
        if "launcher" in name and suffix in name and name.endswith(".zip"):
            return asset.get("browser_download_url", "")

    # 其次找 worker zip
    for asset in assets:
        name = asset.get("name", "")
        if "worker" in name and suffix in name and name.endswith(".zip"):
            return asset.get("browser_download_url", "")

    return ""
