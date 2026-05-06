"""SSUBB 字幕预览脚本

读取 SRT 字幕文件，展示元数据、前 N 条内容、质量统计。

使用方法:
    python scripts/preview.py path/to/subtitle.srt
    python scripts/preview.py path/to/subtitle.srt --head 20 --tail 5
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.terminal import console, Section, KV


# =============================================================================
# SRT 解析
# =============================================================================

_SRT_BLOCK = re.compile(
    r"(\d+)\s*\n"
    r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n"
    r"([\s\S]*?)(?=\n\d+\n|\Z)",
    re.MULTILINE,
)


def _ts_to_sec(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_srt(text: str) -> list[dict]:
    """解析 SRT 文本，返回 [{index, start, end, text}]"""
    entries = []
    for m in _SRT_BLOCK.finditer(text):
        entries.append({
            "index": int(m.group(1)),
            "start": m.group(2),
            "end": m.group(3),
            "start_sec": _ts_to_sec(m.group(2)),
            "end_sec": _ts_to_sec(m.group(3)),
            "text": m.group(4).strip(),
        })
    return entries


# =============================================================================
# 统计
# =============================================================================

def compute_stats(entries: list[dict], file_size_kb: float) -> dict:
    """计算字幕统计信息"""
    if not entries:
        return {"count": 0}

    durations = [e["end_sec"] - e["start_sec"] for e in entries]
    text_lens = [len(e["text"]) for e in entries]

    # 检测是否有中文
    has_cjk = any(
        "一" <= ch <= "鿿"
        for e in entries
        for ch in e["text"]
    )

    # 检测双语（每条字幕含多行且不同语言特征）
    bilingual = sum(
        1 for e in entries
        if "\n" in e["text"] and
        any("一" <= c <= "鿿" for c in e["text"]) and
        any("a" <= c.lower() <= "z" for c in e["text"])
    )

    total_dur = entries[-1]["end_sec"] if entries else 0
    density = len(entries) / (total_dur / 60) if total_dur > 0 else 0

    return {
        "count": len(entries),
        "duration_sec": total_dur,
        "density": density,
        "has_cjk": has_cjk,
        "bilingual_count": bilingual,
        "avg_len": sum(text_lens) / len(text_lens) if text_lens else 0,
        "max_len": max(text_lens) if text_lens else 0,
        "file_size_kb": file_size_kb,
    }


# =============================================================================
# 输出
# =============================================================================

def print_entries(entries: list[dict], *, head: int = 10, tail: int = 3) -> None:
    """打印字幕条目（前 N + 后 M）"""
    total = len(entries)
    show_all = total <= head + tail

    for e in (entries if show_all else entries[:head]):
        _print_one(e)

    if not show_all:
        console.info(f"... 省略 {total - head - tail} 条 ...")
        for e in entries[-tail:]:
            _print_one(e)


def _print_one(e: dict) -> None:
    idx = e["index"]
    ts = f"{e['start']} → {e['end']}"
    text = e["text"].replace("\n", " / ")
    print(f"    {idx:>4}  {ts}  {text}")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="SSUBB 字幕预览")
    parser.add_argument("file", help="SRT 文件路径")
    parser.add_argument("--head", type=int, default=10, help="显示前 N 条 (默认 10)")
    parser.add_argument("--tail", type=int, default=3, help="显示后 N 条 (默认 3)")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        console.fail(f"文件不存在: {path}")
        sys.exit(1)

    text = path.read_text(encoding="utf-8-sig")
    entries = parse_srt(text)
    stats = compute_stats(entries, path.stat().st_size / 1024)

    console.h1(f"字幕预览 — {path.name}")

    with Section("元数据"):
        KV("条目数", str(stats["count"]))
        if stats["count"] > 0:
            dur = stats["duration_sec"]
            KV("时长", f"{int(dur//3600):02d}:{int(dur%3600//60):02d}:{int(dur%60):02d}")
            KV("密度", f"{stats['density']:.1f} 条/分钟")
            KV("平均行长", f"{stats['avg_len']:.0f} 字符")
            KV("最长行", f"{stats['max_len']} 字符")
            KV("语言", "中英双语" if stats["bilingual_count"] > stats["count"] * 0.3 else
               "中文" if stats["has_cjk"] else "英文")
            KV("文件大小", f"{stats['file_size_kb']:.1f} KB")

    if entries:
        console.blank()
        console.h2("字幕内容")
        print_entries(entries, head=args.head, tail=args.tail)
    else:
        console.warn("未解析到有效字幕条目")


if __name__ == "__main__":
    main()
