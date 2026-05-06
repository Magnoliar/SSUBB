"""SSUBB LLM 翻译性能基准测试

向配置的 LLM 端点发送翻译请求，测量延迟和吞吐量。

使用方法:
    python scripts/benchmark_llm.py
    python scripts/benchmark_llm.py --api-base https://api.deepseek.com/v1 --api-key sk-xxx --model deepseek-chat
    python scripts/benchmark_llm.py --config worker/config.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.terminal import console, Section, KV, Confirm


# 测试用字幕片段
SAMPLE_SEGMENTS = [
    "Previously on Breaking Bad...",
    "I am the one who knocks!",
    "Say my name.",
    "You're goddamn right.",
    "I am not in danger, Skyler. I am the danger.",
    "We need to cook.",
    "Tread lightly.",
    "This is my own private domicile and I will not be harassed!",
    "Yeah, science!",
    "No more half measures.",
]


def load_config(config_path: str | None) -> dict:
    """从配置文件加载 LLM 设置"""
    if not config_path:
        return {}
    p = Path(config_path)
    if not p.exists():
        return {}
    try:
        import yaml
        cfg = yaml.safe_load(p.read_text())
        llm = cfg.get("worker", {}).get("llm", {})
        providers = cfg.get("worker", {}).get("llm_providers", [])
        if providers:
            best = min(providers, key=lambda x: x.get("priority", 99))
            return {
                "api_base": best.get("api_base", ""),
                "api_key": best.get("api_key", ""),
                "model": best.get("model", ""),
            }
        return llm
    except Exception as e:
        console.warn(f"配置读取失败: {e}")
        return {}


def benchmark_translation(
    api_base: str,
    api_key: str,
    model: str,
    segments: list[str],
    *,
    iterations: int = 3,
) -> dict | None:
    """执行翻译基准测试"""
    try:
        from openai import OpenAI
    except ImportError:
        console.fail("openai 库未安装")
        return None

    client = OpenAI(base_url=api_base, api_key=api_key)
    text_block = "\n".join(f"[{i+1}] {s}" for i, s in enumerate(segments))

    prompt = f"""Translate each line to Chinese. Return JSON array only.

{text_block}

Output format: [{{"id": 1, "translation": "译文"}}]"""

    latencies = []
    token_counts = []

    for i in range(iterations):
        console.info(f"迭代 {i+1}/{iterations}...")
        t0 = time.time()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a professional subtitle translator. Output JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=2000,
            )
            latency = time.time() - t0
            latencies.append(latency)
            usage = resp.usage
            token_counts.append({
                "prompt": usage.prompt_tokens if usage else 0,
                "completion": usage.completion_tokens if usage else 0,
            })
        except Exception as e:
            console.fail(f"请求失败: {e}")
            return None

    avg_latency = sum(latencies) / len(latencies)
    avg_tokens = {
        "prompt": sum(t["prompt"] for t in token_counts) / len(token_counts),
        "completion": sum(t["completion"] for t in token_counts) / len(token_counts),
    }
    throughput = avg_tokens["completion"] / avg_latency if avg_latency > 0 else 0

    return {
        "model": model,
        "api_base": api_base,
        "iterations": iterations,
        "avg_latency": avg_latency,
        "min_latency": min(latencies),
        "max_latency": max(latencies),
        "avg_prompt_tokens": avg_tokens["prompt"],
        "avg_completion_tokens": avg_tokens["completion"],
        "throughput_tps": throughput,
        "segment_count": len(segments),
    }


def main():
    parser = argparse.ArgumentParser(description="SSUBB LLM 基准测试")
    parser.add_argument("--api-base", help="API 地址")
    parser.add_argument("--api-key", help="API Key")
    parser.add_argument("--model", help="模型名")
    parser.add_argument("--config", default="worker/config.yaml", help="配置文件路径")
    parser.add_argument("--iterations", type=int, default=3, help="测试迭代次数")
    args = parser.parse_args()

    # 加载配置
    cfg = load_config(args.config)
    api_base = args.api_base or cfg.get("api_base", "")
    api_key = args.api_key or cfg.get("api_key", "")
    model = args.model or cfg.get("model", "")

    if not all([api_base, api_key, model]):
        console.fail("缺少 API 配置。请通过参数或 --config 指定。")
        console.info("用法: python scripts/benchmark_llm.py --api-base URL --api-key KEY --model MODEL")
        sys.exit(1)

    console.h1("LLM 翻译基准测试")
    with Section("配置"):
        KV("API 地址", api_base)
        KV("模型", model)
        KV("测试段数", str(len(SAMPLE_SEGMENTS)))
        KV("迭代次数", str(args.iterations))

    console.blank()
    if not Confirm("开始测试？"):
        return

    console.blank()
    result = benchmark_translation(
        api_base, api_key, model, SAMPLE_SEGMENTS,
        iterations=args.iterations,
    )

    if not result:
        console.fail("测试失败")
        sys.exit(1)

    console.h2("测试结果")
    KV("平均延迟", f"{result['avg_latency']:.2f}s")
    KV("最快", f"{result['min_latency']:.2f}s")
    KV("最慢", f"{result['max_latency']:.2f}s")
    KV("平均输入 Token", f"{result['avg_prompt_tokens']:.0f}")
    KV("平均输出 Token", f"{result['avg_completion_tokens']:.0f}")
    KV("吞吐量", f"{result['throughput_tps']:.1f} token/s")
    KV("翻译速率", f"{result['segment_count'] / result['avg_latency']:.1f} 段/秒")


if __name__ == "__main__":
    main()
