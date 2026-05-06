"""SSUBB 升级兼容性测试

验证数据库迁移、配置兼容性、模型序列化等升级路径。

使用方法:
    python scripts/test_upgrade.py
    python scripts/test_upgrade.py --config worker/config.yaml
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.terminal import console, Section, KV


# =============================================================================
# 数据库迁移测试
# =============================================================================

def test_db_migration(db_path: str) -> bool:
    """测试数据库迁移是否安全"""
    from coordinator.task_store import TaskStore

    console.info(f"测试数据库: {db_path}")

    try:
        store = TaskStore(db_path)
    except Exception as e:
        console.fail(f"数据库初始化失败: {e}")
        return False

    # 创建任务
    from shared.models import TaskCreate
    task_in = TaskCreate(media_path="/test/movie.mkv", media_title="Test Movie")
    try:
        task = store.create_task(task_in)
        task_id = task.id
        console.ok(f"创建任务成功: {task_id}")
    except Exception as e:
        console.fail(f"创建任务失败: {e}")
        return False

    # 查询任务
    task = store.get_task(task_id)
    if task is None:
        console.fail("查询任务失败: 返回 None")
        return False
    console.ok(f"查询任务成功: {task.media_path}")

    # 更新状态
    try:
        store.update_status(task_id, "extracting", progress=20)
        task2 = store.get_task(task_id)
        if task2 and task2.status == "extracting" and task2.progress == 20:
            console.ok("状态更新成功")
        else:
            console.fail("状态更新后数据不一致")
            return False
    except Exception as e:
        console.fail(f"状态更新失败: {e}")
        return False

    # 测试字幕存储
    try:
        store.save_subtitle(task_id, "1\n00:00:01,000 --> 00:00:02,000\nHello\n", None)
        sub = store.get_subtitle(task_id)
        if sub and "Hello" in sub.get("srt_content", ""):
            console.ok("字幕存储/读取成功")
        else:
            console.fail("字幕读取失败")
            return False
    except Exception as e:
        console.fail(f"字幕存储失败: {e}")
        return False

    console.ok("数据库迁移测试全部通过")
    return True


# =============================================================================
# 配置兼容性测试
# =============================================================================

def test_config_compat(config_path: str | None) -> bool:
    """测试配置加载兼容性"""
    if not config_path:
        console.info("未指定配置文件，跳过配置测试")
        return True

    p = Path(config_path)
    if not p.exists():
        console.warn(f"配置文件不存在: {p}")
        return True

    try:
        import yaml
        raw = yaml.safe_load(p.read_text())
    except Exception as e:
        console.fail(f"YAML 解析失败: {e}")
        return False

    # 检查旧格式 → 新格式的兼容性
    worker = raw.get("worker", {})
    llm = worker.get("llm", {})
    providers = worker.get("llm_providers", [])

    if llm.get("api_key") and not providers:
        console.ok("旧格式 llm 配置 → 将自动迁移为 llm_providers")
    elif providers:
        console.ok(f"llm_providers 配置: {len(providers)} 个提供商")

    coord = raw.get("coordinator", {})
    workers = coord.get("workers", [])
    old_worker = coord.get("worker", {})

    if old_worker.get("url") and not workers:
        console.ok("旧格式 worker.url → 将自动迁移为 workers 列表")
    elif workers:
        console.ok(f"workers 配置: {len(workers)} 个节点")

    # 检查安全配置
    security = coord.get("security", {})
    if security.get("api_token"):
        console.ok("API Token 已配置")
    else:
        console.warn("API Token 未配置（建议生产环境设置）")

    console.ok("配置兼容性检查通过")
    return True


# =============================================================================
# 模型序列化测试
# =============================================================================

def test_model_serialization() -> bool:
    """测试 Pydantic 模型序列化/反序列化"""
    from shared.models import (
        TaskCreate, TaskConfig, TaskInfo, WorkerTaskResult,
        WorkerHeartbeat, LLMProviderConfig,
    )

    all_ok = True

    # TaskCreate
    try:
        tc = TaskCreate(media_path="/test.mkv", priority=1, annotation="auto")
        d = tc.model_dump()
        assert d["priority"] == 1
        assert d["annotation"] == "auto"
        console.ok("TaskCreate 序列化")
    except Exception as e:
        console.fail(f"TaskCreate: {e}")
        all_ok = False

    # TaskConfig with glossary
    try:
        cfg = TaskConfig(
            glossary={"Walter": "沃尔特", "Jesse": "杰西"},
            annotation="on",
            annotation_quality_threshold=80,
        )
        d = cfg.model_dump()
        assert d["glossary"]["Walter"] == "沃尔特"
        assert d["annotation"] == "on"
        console.ok("TaskConfig 序列化（含术语表 + 注释配置）")
    except Exception as e:
        console.fail(f"TaskConfig: {e}")
        all_ok = False

    # WorkerTaskResult
    try:
        r = WorkerTaskResult(
            task_id="test123",
            status="completed",
            subtitle_srt="1\n00:00:01,000 --> 00:00:02,000\nHello\n",
            annotations=[{"index": 1, "start": "00:00:01", "end": "00:00:02", "text": "注释"}],
            cultural_density="high",
        )
        d = r.model_dump()
        assert d["cultural_density"] == "high"
        assert len(d["annotations"]) == 1
        console.ok("WorkerTaskResult 序列化（含注释）")
    except Exception as e:
        console.fail(f"WorkerTaskResult: {e}")
        all_ok = False

    # LLMProviderConfig
    try:
        p = LLMProviderConfig(api_base="https://api.test.com/v1", api_key="sk-xxx", model="test", priority=2)
        d = p.model_dump()
        assert d["priority"] == 2
        assert d["enabled"] is True
        console.ok("LLMProviderConfig 序列化")
    except Exception as e:
        console.fail(f"LLMProviderConfig: {e}")
        all_ok = False

    # TaskInfo 完整性
    try:
        ti = TaskInfo(media_path="/test.mkv", status="pending", priority=3)
        d = ti.model_dump()
        assert len(d["id"]) == 12
        assert d["status"] == "pending"
        console.ok("TaskInfo 序列化")
    except Exception as e:
        console.fail(f"TaskInfo: {e}")
        all_ok = False

    return all_ok


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="SSUBB 升级兼容性测试")
    parser.add_argument("--config", default=None, help="配置文件路径")
    args = parser.parse_args()

    console.h1("SSUBB 升级兼容性测试")
    passed = 0
    total = 0

    # 数据库迁移
    with Section("数据库迁移"):
        total += 1
        import gc
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            if test_db_migration(db_path):
                passed += 1
        finally:
            gc.collect()  # 释放 SQLite 连接
            try:
                os.unlink(db_path)
            except OSError:
                pass

    # 配置兼容性
    with Section("配置兼容性"):
        total += 1
        if test_config_compat(args.config):
            passed += 1

    # 模型序列化
    with Section("模型序列化"):
        total += 1
        if test_model_serialization():
            passed += 1

    # 汇总
    console.blank()
    if passed == total:
        console.ok(f"全部通过 ({passed}/{total})")
    else:
        console.warn(f"通过 {passed}/{total}")
        sys.exit(1)


if __name__ == "__main__":
    main()
