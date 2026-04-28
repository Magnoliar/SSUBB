"""SSUBB Worker - 首次配置引导

交互式生成 config.yaml 中的 Worker 配置。
用法: python -m worker.setup_wizard
"""

import os
import sys
from pathlib import Path

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _input(prompt: str, default: str = "") -> str:
    """带默认值的输入"""
    if default:
        raw = input(f"  {prompt} [{default}]: ").strip()
        return raw or default
    else:
        return input(f"  {prompt}: ").strip()


def _confirm(prompt: str, default: bool = True) -> bool:
    """确认提示"""
    suffix = "[Y/n]" if default else "[y/N]"
    raw = input(f"  {prompt} {suffix}: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def run_wizard():
    """交互式配置引导"""
    print()
    print("=" * 60)
    print("  SSUBB Worker 配置引导")
    print("=" * 60)
    print()
    print("  本向导将帮助你生成 Worker 端配置。")
    print("  按 Enter 使用默认值。")
    print()

    # ---- 基本信息 ----
    print("── 基本信息 ─────────────────────────────────")
    worker_id = _input("Worker 节点标识", "office-gpu")
    coordinator_url = _input("Coordinator 地址 (NAS 端)", "http://192.168.1.10:8787")

    # ---- GPU / 转写 ----
    print("\n── 转写配置 ─────────────────────────────────")

    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            print(f"  ✅ 检测到 GPU: {gpu_name}")
            device = "cuda"
            compute_type = "float16"
        else:
            print("  ⚠️ 未检测到 CUDA GPU，将使用 CPU 模式")
            device = "cpu"
            compute_type = "int8"
    except ImportError:
        print("  ⚠️ PyTorch 未安装，默认 CPU 模式")
        device = "cpu"
        compute_type = "int8"

    device = _input("设备", device)
    compute_type = _input("计算精度 (float16/int8/float32)", compute_type)
    model = _input("Whisper 模型", "large-v3-turbo")
    model_dir = _input("模型缓存目录", "./models")

    # ---- LLM ----
    print("\n── LLM 翻译配置 ──────────────────────────────")
    print("  翻译和断句优化需要 OpenAI 兼容的 LLM API。")
    api_base = _input("LLM API 地址", "https://api.deepseek.com/v1")
    api_key = _input("LLM API Key", "")
    llm_model = _input("LLM 模型名称", "deepseek-chat")

    # ---- 翻译 ----
    print("\n── 翻译选项 ──────────────────────────────────")
    target_lang = _input("目标语言", "zh")
    thread_num = _input("翻译并发数", "5")
    batch_size = _input("每批翻译条数", "10")
    need_reflect = _confirm("启用反思翻译 (更高质量，更慢)", False)

    # ---- 确认 ----
    print("\n── 生成配置 ──────────────────────────────────")

    config_content = f"""# =============================================================================
# SSUBB Worker 配置 (由 setup_wizard 生成)
# =============================================================================

worker:
  host: "0.0.0.0"
  port: 8788
  worker_id: "{worker_id}"
  coordinator_url: "{coordinator_url}"

  transcribe:
    model: "{model}"
    device: "{device}"
    compute_type: "{compute_type}"
    concurrent_transcriptions: 1
    vad_filter: true
    vad_method: "silero_v4_fw"
    vad_threshold: 0.5
    custom_regroup: "cm_sl=84_sl=42++++++1"
    detect_language_length: 30
    model_dir: "{model_dir}"

  llm:
    api_base: "{api_base}"
    api_key: "{api_key}"
    model: "{llm_model}"

  translate:
    service: "llm"
    target_language: "{target_lang}"
    thread_num: {thread_num}
    batch_size: {batch_size}
    need_reflect: {str(need_reflect).lower()}

  optimize:
    enabled: true
    max_word_count_cjk: 12
    max_word_count_english: 18

  vram:
    clear_on_complete: true
    cleanup_delay: 30

  temp_dir: "./data/worker_temp"
"""

    config_path = PROJECT_ROOT / "config.yaml"

    print(f"\n  配置预览:")
    print("  " + "-" * 50)
    for line in config_content.strip().split("\n"):
        # 隐藏 API key 的完整值
        if "api_key:" in line and api_key:
            display_key = api_key[:8] + "..." if len(api_key) > 8 else api_key
            line = line.replace(api_key, display_key)
        print(f"  {line}")
    print("  " + "-" * 50)

    if config_path.exists():
        print(f"\n  ⚠️ 已存在 {config_path}")
        if not _confirm("是否覆盖?", False):
            # 保存到备用路径
            alt_path = PROJECT_ROOT / "config.worker.yaml"
            alt_path.write_text(config_content, encoding="utf-8")
            print(f"\n  ✅ 配置已保存到: {alt_path}")
            print(f"  手动合并到 config.yaml 后即可使用。")
            return
    
    config_path.write_text(config_content, encoding="utf-8")
    print(f"\n  ✅ 配置已保存到: {config_path}")

    # ---- 环境检查 ----
    print()
    if _confirm("是否运行环境检查?", True):
        from worker.env_check import run_full_check, print_check_report
        from worker.config import load_worker_config
        try:
            cfg = load_worker_config(str(config_path))
            results = run_full_check(cfg)
            print_check_report(results)
        except Exception as e:
            print(f"  环境检查出错: {e}")

    # ---- 模型下载 ----
    if _confirm(f"是否现在下载 Whisper 模型 ({model})?", True):
        from worker.model_manager import ModelManager
        mgr = ModelManager(model_dir)
        if mgr.is_installed(model):
            print(f"  ✅ 模型 {model} 已存在，无需下载。")
        else:
            print(f"  正在下载 {model}...")
            if mgr.download_model(model):
                print(f"  ✅ 模型下载完成！")
            else:
                print(f"  ⚠️ 自动下载失败，模型将在首次转写时自动下载。")

    print("\n" + "=" * 60)
    print("  配置完成！启动 Worker:")
    print(f"    python -m uvicorn worker.main:app --host 0.0.0.0 --port 8788")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_wizard()
