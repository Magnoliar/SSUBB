"""SSUBB Whisper 转写性能基准测试

在本地音频文件上运行 Whisper 转写，测量不同模型的耗时和准确率。

使用方法:
    python scripts/benchmark_whisper.py audio.flac
    python scripts/benchmark_whisper.py audio.flac --models base,small,large-v3-turbo
    python scripts/benchmark_whisper.py audio.flac --device cpu --compute-type int8
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.terminal import console, Section, KV, Confirm


MODELS = ["tiny", "base", "small", "medium", "large-v3-turbo"]


def benchmark_model(
    audio_path: str,
    model_name: str,
    *,
    device: str = "cuda",
    compute_type: str = "float16",
) -> dict | None:
    """对单个模型执行转写基准测试"""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        console.fail("faster-whisper 未安装")
        return None

    console.info(f"加载模型 {model_name} ({device}, {compute_type})...")
    t0 = time.time()
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
    except Exception as e:
        console.fail(f"模型加载失败: {e}")
        return None
    load_time = time.time() - t0

    console.info("转写中...")
    t0 = time.time()
    try:
        segments, info = model.transcribe(
            audio_path,
            language=None,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        seg_list = list(segments)
    except Exception as e:
        console.fail(f"转写失败: {e}")
        return None
    transcribe_time = time.time() - t0

    total_chars = sum(len(s.text.strip()) for s in seg_list)
    return {
        "model": model_name,
        "device": device,
        "compute_type": compute_type,
        "load_time": load_time,
        "transcribe_time": transcribe_time,
        "segment_count": len(seg_list),
        "total_chars": total_chars,
        "detected_lang": info.language,
        "lang_prob": info.language_probability,
    }


def main():
    parser = argparse.ArgumentParser(description="SSUBB Whisper 基准测试")
    parser.add_argument("audio", help="音频文件路径 (flac/wav/mp3)")
    parser.add_argument("--models", default=",".join(MODELS), help="逗号分隔的模型列表")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu", "auto"])
    parser.add_argument("--compute-type", default="float16", choices=["float16", "int8", "float32"])
    args = parser.parse_args()

    audio = Path(args.audio)
    if not audio.exists():
        console.fail(f"文件不存在: {audio}")
        sys.exit(1)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    console.h1(f"Whisper 基准测试 — {audio.name}")
    KV("文件大小", f"{audio.stat().st_size / 1024 / 1024:.1f} MB")
    KV("设备", args.device)
    KV("精度", args.compute_type)
    KV("模型数", str(len(models)))
    console.blank()

    if not Confirm("开始测试？"):
        return

    results = []
    for i, model_name in enumerate(models, 1):
        console.h2(f"[{i}/{len(models)}] {model_name}")
        r = benchmark_model(str(audio), model_name, device=args.device, compute_type=args.compute_type)
        if r:
            results.append(r)
            KV("加载耗时", f"{r['load_time']:.1f}s")
            KV("转写耗时", f"{r['transcribe_time']:.1f}s")
            KV("字幕条数", str(r["segment_count"]))
            KV("总字符数", str(r["total_chars"]))
            KV("检测语言", f"{r['detected_lang']} ({r['lang_prob']:.0%})")
        console.blank()

    # 汇总
    if results:
        console.h2("性能汇总")
        best = min(results, key=lambda r: r["transcribe_time"])
        for r in sorted(results, key=lambda r: r["transcribe_time"]):
            speed = r["transcribe_time"]
            marker = " ← 最快" if r is best else ""
            print(f"    {r['model']:<22} {speed:>6.1f}s  ({r['segment_count']} 条, {r['total_chars']} 字){marker}")


if __name__ == "__main__":
    main()
