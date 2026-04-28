"""SSUBB Smoke Test - 基础连通性与功能验证

用法:
    python tests/smoke_test.py [--coordinator http://127.0.0.1:8787] [--worker http://127.0.0.1:8788]

说明:
    - 不依赖真实媒体文件，只验证 API 端点、数据库、配置加载等基础能力
    - 可单独测 Coordinator 或 Worker（对方不在线时跳过跨节点测试）
    - 适合部署后快速检查系统是否正常
"""

import argparse
import json
import sys
import time
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import httpx
except ImportError:
    print("ERROR: httpx 未安装, 请运行: pip install httpx")
    sys.exit(1)


class SmokeTest:
    def __init__(self, coordinator_url: str, worker_url: str):
        self.coord_url = coordinator_url.rstrip("/")
        self.worker_url = worker_url.rstrip("/")
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.client = httpx.Client(timeout=10.0)

    def run_all(self):
        print("=" * 60)
        print("  SSUBB Smoke Test")
        print("=" * 60)
        print()

        # ---- 模块导入测试 ----
        self._section("模块导入")
        self._test_import("shared.constants", "from shared.constants import TaskStatus, ErrorCode")
        self._test_import("shared.models", "from shared.models import TaskInfo, TaskConfig")
        self._test_import("coordinator.config", "from coordinator.config import load_config")
        self._test_import("coordinator.task_store", "from coordinator.task_store import TaskStore")
        self._test_import("coordinator.task_manager", "from coordinator.task_manager import TaskManager")
        self._test_import("coordinator.scanner", "from coordinator.scanner import MediaScanner")
        self._test_import("coordinator.scheduler", "from coordinator.scheduler import AutoScheduler")
        self._test_import("worker.env_check", "from worker.env_check import run_full_check, EnvCheckResult")
        self._test_import("worker.model_manager", "from worker.model_manager import ModelManager, KNOWN_MODELS")

        # ---- 配置加载测试 ----
        self._section("配置加载")
        self._test_config_load()

        # ---- 数据库测试 ----
        self._section("数据库")
        self._test_db_operations()

        # ---- Coordinator API 测试 ----
        self._section("Coordinator API")
        coord_online = self._test_endpoint(self.coord_url, "/api/status", "系统状态")
        if coord_online:
            self._test_endpoint(self.coord_url, "/api/tasks", "任务列表")
            self._test_endpoint(self.coord_url, "/api/logs?lines=5", "日志接口")
            self._test_endpoint(self.coord_url, "/api/fs", "文件浏览器")
            self._test_endpoint(self.coord_url, "/", "WebUI 页面")
            self._test_status_fields()
            self._test_tasks_response()
        else:
            self._skip("Coordinator 未启动，跳过 API 测试")

        # ---- Worker API 测试 ----
        self._section("Worker API")
        worker_online = self._test_endpoint(self.worker_url, "/api/status", "Worker 状态")
        if worker_online:
            self._test_endpoint(self.worker_url, "/docs", "Worker Swagger")
        else:
            self._skip("Worker 未启动，跳过 Worker API 测试")

        # ---- 跨节点连通性 ----
        self._section("跨节点连通性")
        if coord_online:
            self._test_cross_node_connectivity()
        else:
            self._skip("Coordinator 未启动，跳过跨节点测试")

        # ---- 结果汇总 ----
        self._summary()

    # =========================================================================
    # 测试用例
    # =========================================================================

    def _test_import(self, name: str, import_stmt: str):
        try:
            exec(import_stmt)
            self._pass(f"导入 {name}")
        except Exception as e:
            self._fail(f"导入 {name}", str(e))

    def _test_config_load(self):
        try:
            from coordinator.config import load_config
            config = load_config()
            assert config.port == 8787 or config.port > 0, "端口配置异常"
            assert config.db_path, "数据库路径为空"
            assert config.stage_timeout.extracting > 0, "超时配置异常"
            self._pass("配置加载 (含 stage_timeout)")

            # 自动化配置
            assert hasattr(config, 'automation'), "缺少 automation 配置"
            assert hasattr(config.automation, 'scan_paths'), "缺少 scan_paths"
            assert hasattr(config.automation, 'schedule_start'), "缺少 schedule_start"
            self._pass("自动化配置 (AutomationConfig)")

            # V0.4 字幕输出配置
            assert hasattr(config.subtitle, 'output_mode'), "缺少 output_mode"
            assert hasattr(config.subtitle, 'output_format'), "缺少 output_format"
            assert config.subtitle.output_mode in ('single', 'bilingual'), f"无效 output_mode: {config.subtitle.output_mode}"
            assert config.subtitle.output_format in ('srt', 'ass'), f"无效 output_format: {config.subtitle.output_format}"
            self._pass("字幕输出配置 (output_mode/format)")

        except Exception as e:
            self._fail("配置加载", str(e))

    def _test_db_operations(self):
        """测试数据库 CRUD"""
        import tempfile, os
        try:
            from coordinator.task_store import TaskStore
            from shared.models import TaskCreate
            from shared.constants import TaskStatus

            # 使用临时数据库
            db_path = os.path.join(tempfile.gettempdir(), "ssubb_smoke_test.db")
            store = TaskStore(db_path)

            # 创建任务
            req = TaskCreate(media_path="/test/smoke.mp4", target_lang="zh")
            task = store.create_task(req)
            assert task.id, "任务 ID 为空"
            assert task.status == TaskStatus.PENDING, f"初始状态异常: {task.status}"
            self._pass("创建任务")

            # 读取任务
            fetched = store.get_task(task.id)
            assert fetched is not None, "读取任务失败"
            assert fetched.media_path == "/test/smoke.mp4"
            self._pass("读取任务")

            # 更新状态 (含新字段)
            store.update_status(
                task.id, TaskStatus.FAILED,
                error_msg="测试错误",
                error_code="test_error",
                failed_stage="extracting",
            )
            updated = store.get_task(task.id)
            assert updated.status == TaskStatus.FAILED
            assert updated.error_code == "test_error"
            assert updated.failed_stage == "extracting"
            self._pass("更新状态 (含 error_code/failed_stage)")

            # 阶段耗时
            store.update_stage_time(task.id, "extracting", 12.34)
            timed = store.get_task(task.id)
            assert timed.stage_times.get("extracting") == 12.34
            self._pass("阶段耗时记录")

            # 重试重置
            store.reset_for_retry(task.id)
            retried = store.get_task(task.id)
            assert retried.status == TaskStatus.PENDING
            assert retried.error_msg is None
            assert retried.retry_count == 1
            self._pass("重试重置")

            # 统计
            stats = store.count_by_status()
            assert isinstance(stats, dict)
            self._pass("状态统计")

            # 清理
            try:
                os.unlink(db_path)
            except:
                pass

        except Exception as e:
            self._fail("数据库操作", str(e))

    def _test_endpoint(self, base_url: str, path: str, name: str) -> bool:
        try:
            res = self.client.get(f"{base_url}{path}")
            if res.status_code == 200:
                self._pass(f"{name} ({path}) → {res.status_code}")
                return True
            else:
                self._fail(f"{name} ({path})", f"HTTP {res.status_code}")
                return True  # 服务在线但端点异常
        except httpx.ConnectError:
            self._skip(f"{name} — 服务未启动")
            return False
        except Exception as e:
            self._fail(f"{name} ({path})", str(e))
            return False

    def _test_status_fields(self):
        """验证 /api/status 返回完整字段"""
        try:
            res = self.client.get(f"{self.coord_url}/api/status")
            data = res.json()
            required = ["version", "coordinator_online", "tasks_pending", "tasks_active",
                        "tasks_completed", "tasks_failed"]
            missing = [f for f in required if f not in data]
            if missing:
                self._fail("状态字段完整性", f"缺少: {missing}")
            else:
                self._pass(f"状态字段完整性 (version={data['version']})")
        except Exception as e:
            self._fail("状态字段完整性", str(e))

    def _test_tasks_response(self):
        """验证 /api/tasks 返回 {total, tasks} 结构"""
        try:
            res = self.client.get(f"{self.coord_url}/api/tasks?limit=5")
            data = res.json()
            assert "total" in data, "缺少 total 字段"
            assert "tasks" in data, "缺少 tasks 字段"
            assert isinstance(data["tasks"], list), "tasks 不是列表"
            self._pass(f"任务列表结构 (total={data['total']}, count={len(data['tasks'])})")

            # 验证新字段
            if data["tasks"]:
                t = data["tasks"][0]
                new_fields = ["error_code", "failed_stage", "stage_times", "result_summary"]
                present = [f for f in new_fields if f in t]
                self._pass(f"TaskInfo 新字段 ({len(present)}/{len(new_fields)} 个)")
        except Exception as e:
            self._fail("任务列表结构", str(e))

    def _test_cross_node_connectivity(self):
        """通过 Coordinator 的 status 检查 Worker 连通性"""
        try:
            res = self.client.get(f"{self.coord_url}/api/status")
            data = res.json()
            worker = data.get("worker")
            if worker:
                if worker.get("online"):
                    hb = worker.get("heartbeat", {})
                    self._pass(
                        f"Coordinator→Worker 连通 "
                        f"(GPU: {hb.get('gpu_name', '?')}, "
                        f"VRAM: {hb.get('vram_used_mb', '?')}M/{hb.get('vram_total_mb', '?')}M)"
                    )
                else:
                    self._skip(f"Worker 离线 (url: {worker.get('url', '?')})")
            else:
                self._skip("Worker 未配置")
        except Exception as e:
            self._fail("跨节点连通性", str(e))

    # =========================================================================
    # 输出格式
    # =========================================================================

    def _section(self, name: str):
        print(f"\n── {name} {'─' * (50 - len(name))}")

    def _pass(self, msg: str):
        self.passed += 1
        print(f"  ✅ {msg}")

    def _fail(self, msg: str, detail: str = ""):
        self.failed += 1
        print(f"  ❌ {msg}")
        if detail:
            print(f"     └─ {detail}")

    def _skip(self, msg: str):
        self.skipped += 1
        print(f"  ⏭️  {msg}")

    def _summary(self):
        total = self.passed + self.failed + self.skipped
        print()
        print("=" * 60)
        print(f"  结果: {self.passed} 通过 / {self.failed} 失败 / {self.skipped} 跳过 (共 {total})")
        if self.failed == 0:
            print("  🎉 Smoke Test 通过!")
        else:
            print("  ⚠️  存在失败项，请检查")
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="SSUBB Smoke Test")
    parser.add_argument("--coordinator", default="http://127.0.0.1:8787",
                        help="Coordinator 地址")
    parser.add_argument("--worker", default="http://127.0.0.1:8788",
                        help="Worker 地址")
    args = parser.parse_args()

    test = SmokeTest(args.coordinator, args.worker)
    test.run_all()
    sys.exit(1 if test.failed > 0 else 0)


if __name__ == "__main__":
    main()
