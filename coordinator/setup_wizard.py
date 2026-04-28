"""SSUBB Coordinator - 首次配置引导

交互式生成 config.yaml 中的 Coordinator 配置。
用法: python -m coordinator.setup_wizard
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
    print("  SSUBB Coordinator 配置引导 (NAS 端)")
    print("=" * 60)
    print()
    print("  本向导将帮助你生成 Coordinator 端配置。")
    print("  按 Enter 使用默认值。")
    print()

    # ---- 基本连接 ----
    print("── 核心连接配置 ──────────────────────────────")
    worker_url = _input("GPU Worker 地址 (如 http://192.168.1.50:8788)", "")
    if not worker_url:
        print("  ⚠️ 警告: 未填写 Worker 地址。你稍后需要在 config.yaml 或 WebUI 中配置。")

    # ---- 字幕偏好 ----
    print("\n── 字幕输出偏好 ──────────────────────────────")
    output_mode = _input("输出模式 (single=单语翻译, bilingual=中英双语)", "bilingual")
    output_format = _input("输出格式 (srt=普通格式, ass=高级样式)", "ass")

    # ---- Emby (可选) ----
    print("\n── Emby/Jellyfin 联动 (可选) ─────────────────")
    print("  填写后，字幕生成完毕会自动通知 Emby 刷新媒体库。")
    emby_server = _input("Emby 服务器地址 (如 http://192.168.1.100:8096)", "")
    emby_api_key = ""
    if emby_server:
        emby_api_key = _input("Emby API Key", "")

    # ---- 自动化 (可选) ----
    print("\n── 自动化扫描 (可选) ──────────────────────────")
    enable_automation = _confirm("是否开启自动化扫描（自动给新下载的视频补字幕）?", False)
    scan_paths_str = ""
    if enable_automation:
        scan_paths_input = _input("媒体库目录 (多个目录用逗号分隔，如 /video/movies,/video/tv)", "")
        if scan_paths_input:
            paths = [p.strip() for p in scan_paths_input.split(",") if p.strip()]
            scan_paths_str = "\n".join([f"      - \"{p}\"" for p in paths])

    # ---- 生成配置 ----
    print("\n── 生成配置 ──────────────────────────────────")

    config_content = f"""# =============================================================================
# SSUBB Coordinator 配置 (由 setup_wizard 生成)
# =============================================================================

coordinator:
  host: "0.0.0.0"
  port: 8787
  db_path: "./data/ssubb.db"

  audio:
    format: "flac"
    sample_rate: 16000
    channels: 1
    temp_dir: "./data/audio_temp"

  worker:
    url: "{worker_url}"
    heartbeat_interval: 30
    heartbeat_timeout: 300

  emby:
    server: "{emby_server}"
    api_key: "{emby_api_key}"

  subtitle:
    target_language: "zh"
    naming_format: "{{video_name}}.{{lang}}.srt"
    backup_existing: true
    output_mode: "{output_mode}"
    output_format: "{output_format}"

  checker:
    min_coverage: 0.7
    min_density: 2.0
    check_language: true

  retry:
    max_retries: 3
    backoff_base: 60
    backoff_multiplier: 2

  stage_timeout:
    extracting: 600
    uploading: 600
    transcribing: 3600
    translating: 1800
    default: 1800
"""

    if enable_automation and scan_paths_str:
        config_content += f"""
  automation:
    enabled: true
    scan_paths:
{scan_paths_str}
    scan_recursive: true
    scan_recent_days: 7
    schedule_start: "02:00"
    schedule_end: "06:00"
    scan_interval: 30
    max_tasks_per_scan: 5
    require_worker_idle: true
    preheat_next_episode: true
"""
    else:
        config_content += """
  automation:
    enabled: false
    scan_paths: []
"""

    config_path = PROJECT_ROOT / "config.yaml"

    if config_path.exists():
        print(f"\n  ⚠️ 已存在 {config_path}")
        if not _confirm("是否覆盖?", False):
            alt_path = PROJECT_ROOT / "config.coordinator.yaml"
            alt_path.write_text(config_content, encoding="utf-8")
            print(f"\n  ✅ 配置已保存到: {alt_path}")
            return
    
    config_path.write_text(config_content, encoding="utf-8")
    print(f"\n  ✅ 配置已保存到: {config_path}")

    print("\n" + "=" * 60)
    print("  配置完成！")
    print("  Docker 用户: docker compose up -d")
    print("  裸机 用户:  python -m uvicorn coordinator.main:app --host 0.0.0.0 --port 8787")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_wizard()
