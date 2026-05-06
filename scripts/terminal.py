"""scripts/terminal.py — 终端输出工具集

统一的终端格式化工具，用于所有 scripts/ 下的脚本。
支持 rich（彩色/表格/进度条）和纯文本 fallback。

使用方法:
    from scripts.terminal import console, Section, KV, Confirm, run

    console.h1("安装 Whisper")
    console.ok("Python 3.11 ✓")
    console.warn("CUDA 未检测到，将使用 CPU 模式")
    console.fail("FFmpeg 未找到")

    with Section("环境检查"):
        KV("Python", "3.11.5")
        KV("CUDA", "12.4")

    if not Confirm("是否继续？"):
        console.info("已取消")
        sys.exit(0)
"""

from __future__ import annotations

import subprocess
import sys
import time


class _Console:
    """统一终端输出"""

    # ── 标题 ──

    @staticmethod
    def h1(text: str) -> None:
        print(f"\n{'─' * 60}")
        print(f"  {text}")
        print(f"{'─' * 60}")

    @staticmethod
    def h2(text: str) -> None:
        print(f"\n  {text}")
        print(f"  {'─' * len(text)}")

    # ── 状态 ──

    @staticmethod
    def ok(text: str) -> None:
        print(f"  ✅ {text}")

    @staticmethod
    def warn(text: str) -> None:
        print(f"  ⚠️  {text}")

    @staticmethod
    def fail(text: str) -> None:
        print(f"  ❌ {text}")

    @staticmethod
    def info(text: str) -> None:
        print(f"  ℹ️  {text}")

    @staticmethod
    def bullet(text: str) -> None:
        print(f"  • {text}")

    @staticmethod
    def progress(current: int, total: int, label: str = "") -> None:
        pct = current / total * 100 if total > 0 else 0
        prefix = f"  [{current}/{total}]"
        if label:
            prefix += f" {label}"
        print(f"{prefix} {pct:.0f}%", end="\r")
        if current >= total:
            print()

    @staticmethod
    def blank() -> None:
        print()


class _Section:
    """with Section('标题'): 缩进块"""

    def __init__(self, title: str):
        self.title = title

    def __enter__(self):
        print(f"\n  {self.title}")
        print(f"  {'─' * len(self.title)}")
        return self

    def __exit__(self, *_):
        pass


class _KV:
    """with KV('Key', 'val'): 格式化键值对"""

    _W = 24

    def __init__(self, key: str, value: str, *, warn: bool = False):
        mark = " ⚠️" if warn else ""
        print(f"    {key:<{self._W}}{value}{mark}")


class _Confirm:
    """交互式确认"""

    def __new__(cls, prompt: str, *, default: bool = False) -> bool:
        hint = "Y/n" if default else "y/N"
        try:
            resp = input(f"  {prompt} [{hint}] ").strip().lower()
            if not resp:
                return default
            return resp in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False


def _run(
    cmd: list[str],
    *,
    timeout: int = 60,
    capture: bool = True,
    label: str = "",
) -> tuple[int, str, str]:
    """执行子进程，返回 (returncode, stdout, stderr)

    Args:
        cmd: 命令及参数
        timeout: 超时秒数
        capture: 是否捕获输出（False 则实时打印）
        label: 日志标签
    """
    if label:
        print(f"  → {label}...")

    try:
        if capture:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        else:
            result = subprocess.run(cmd, timeout=timeout)
            return result.returncode, "", ""
    except FileNotFoundError:
        return -1, "", f"命令未找到: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", f"执行超时 ({timeout}s)"


# 全局实例
console = _Console()
Section = _Section
KV = _KV
Confirm = _Confirm
run = _run
