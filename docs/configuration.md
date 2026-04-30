# SSUBB 配置手册 (V0.10)

## 零配置向导 (推荐)

自 SSUBB V0.5 起，我们强烈推荐使用**内置的交互式配置向导**，你几乎不需要手动编辑任何 YAML 文件。

### Coordinator (NAS 端)
直接使用 Docker Compose 启动（不挂载 `config.yaml` 文件，仅挂载 `data/` 目录），启动后访问 Web 控制台（如 `http://<NAS_IP>:8787`），系统会自动弹出图形化的 **WebUI 配置向导**。填完保存后系统自动热启动。

### Worker (GPU 端)
在 Windows/Linux 下运行 `run_worker.bat` 或 `run_worker.sh`，如果检测到没有配置文件，脚本会在终端中逐步询问你的 LLM API Key、模型等信息，并自动生成完善的 `config.yaml`。

---

## 高级手动配置 (供开发者参考)

如果你需要深度定制（如调整超时时间、数据库路径等），可以参考以下内容。SSUBB 的配置加载遵循以下优先级（高 → 低）：

1. **环境变量** (`SSUBB_*`)
2. **config.yaml** 中的值
3. **代码默认值**

## 环境变量一览

| 环境变量 | 对应配置项 | 说明 |
|---|---|---|
| `SSUBB_CONFIG` | — | 配置文件路径 (默认 `./config.yaml`) |
| `SSUBB_WORKER_URL` | `coordinator.worker.url` | 单 Worker 地址（向后兼容） |
| `SSUBB_WORKER_URLS` | `coordinator.workers` | 多 Worker 地址（逗号分隔） |
| `SSUBB_EMBY_SERVER` | `coordinator.emby.server` | Emby 地址 |
| `SSUBB_EMBY_API_KEY` | `coordinator.emby.api_key` | Emby API Key |
| `SSUBB_DB_PATH` | `coordinator.db_path` | 数据库路径 |
| `SSUBB_COORDINATOR_URL` | `worker.coordinator_url` | Coordinator 回调地址 |
| `SSUBB_WORKER_ID` | `worker.worker_id` | Worker 节点 ID |
| `SSUBB_LLM_API_BASE` | `worker.llm.api_base` | LLM API 地址 |
| `SSUBB_DISCOVERY_ENABLED` | `coordinator.discovery.enabled` | 自动发现开关 (`true`/`false`) |
| `SSUBB_WEBHOOK_TOKEN` | `coordinator.webhook.token` | Webhook 认证 Token |
| `SSUBB_LLM_API_KEY` | `worker.llm.api_key` | LLM API Key |
| `SSUBB_LLM_MODEL` | `worker.llm.model` | LLM 模型名 |

> **安全建议**: 生产环境建议将 `api_key` 等敏感字段通过环境变量注入，不要写在 `config.yaml` 中。

## Coordinator 配置项

### 基础

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `host` | string | `0.0.0.0` | 监听地址 |
| `port` | int | `8787` | 监听端口 |
| `db_path` | string | `./data/ssubb.db` | SQLite 数据库路径 |

### 音频提取 (`audio`)

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `format` | string | `flac` | 输出格式 (`flac` / `wav`) |
| `sample_rate` | int | `16000` | 采样率 (Whisper 要求 16kHz) |
| `channels` | int | `1` | 声道数 (Whisper 要求单声道) |
| `temp_dir` | string | `./data/audio_temp` | 临时音频目录 |

### Worker 节点配置 (`workers`) — V0.6 新增

V0.6 起支持配置多个 Worker 节点。Coordinator 会根据权重和负载自动调度任务。

| 配置项 | 类型 | 默认值 | 必填 | 说明 |
|---|---|---|---|---|
| `url` | string | — | ✅ | Worker HTTP 地址 |
| `worker_id` | string | 自动生成 | | 节点标识 |
| `weight` | int | `1` | | 调度权重（越大越优先分配任务） |
| `enabled` | bool | `true` | | 是否启用 |

示例：

```yaml
coordinator:
  workers:
    - url: "http://192.168.1.50:8788"
      worker_id: "office-4090"
      weight: 3        # 高性能节点，优先分配
    - url: "http://192.168.1.51:8788"
      worker_id: "home-3060"
      weight: 1        # 低性能节点，补充使用
```

> **向后兼容**：如果 `workers` 列表为空但存在旧的 `worker.url` 配置，系统会自动将其迁移为单元素 `workers` 列表。环境变量 `SSUBB_WORKER_URLS` 支持逗号分隔的多个地址。

### Worker 连接（旧格式，向后兼容）

| 配置项 | 类型 | 默认值 | 必填 | 说明 |
|---|---|---|---|---|
| `url` | string | `""` | ✅ | GPU Worker HTTP 地址 |
| `heartbeat_interval` | int | `30` | | 心跳间隔 (秒) |
| `heartbeat_timeout` | int | `300` | | 心跳超时 (秒) |

### Emby 集成 (`emby`)

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `server` | string | `""` | Emby 地址 (留空则跳过刷新) |
| `api_key` | string | `""` | Emby API Key |

### 字幕输出 (`subtitle`)

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `target_language` | string | `zh` | 默认目标语言 |
| `naming_format` | string | `{video_name}.{lang}.srt` | 字幕文件命名格式 |
| `backup_existing` | bool | `true` | 覆盖前是否备份 |

### 字幕质量验证 (`checker`)

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `min_coverage` | float | `0.7` | 最低时长覆盖率 |
| `min_density` | float | `2.0` | 最低密度 (条/分钟) |
| `check_language` | bool | `true` | 是否检测语言匹配 |

### 重试配置 (`retry`)

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `max_retries` | int | `3` | 最大重试次数 |
| `backoff_base` | int | `60` | 基础退避 (秒) |
| `backoff_multiplier` | int | `2` | 退避倍数 |

### 自动化调度 (`automation`) — V0.9 更新

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | bool | `true` | 是否启用自动扫描 |
| `scan_interval` | int | `3600` | 扫描间隔 (秒) |
| `schedule_start` | string | `""` | 调度窗口开始时间 (如 `02:00`) |
| `schedule_end` | string | `""` | 调度窗口结束时间 (如 `08:00`) |
| `timezone` | string | `Asia/Shanghai` | 调度时区 (V0.9 新增) |

示例：

```yaml
coordinator:
  automation:
    enabled: true
    scan_interval: 3600
    schedule_start: "02:00"
    schedule_end: "08:00"
    timezone: "Asia/Shanghai"   # V0.9: 统一时区，避免 UTC 偏移问题
```

> **时区说明**：V0.9 修复了调度器时区 bug。之前非 UTC 时区用户（如 UTC+8）的调度窗口会错位，现在使用 `zoneinfo.ZoneInfo` 做本地时间比较。时区值遵循 IANA 时区数据库格式（如 `Asia/Shanghai`、`America/New_York`）。

### 局域网自动发现 (`discovery`) — V0.7 新增

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | bool | `true` | 是否启用自动发现 |
| `port` | int | `8789` | UDP 广播端口 |
| `auto_register` | bool | `true` | 是否自动注册发现的 Worker |

示例：

```yaml
coordinator:
  discovery:
    enabled: true
    port: 8789
    auto_register: true
```

> **Docker 注意**：自动发现使用 UDP 广播，需要 `--network host` 或映射 UDP 8789 端口。可通过 `SSUBB_DISCOVERY_ENABLED=false` 关闭。

### 通用 Webhook (`webhook`) — V0.8 新增

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | bool | `true` | 是否启用 Webhook 入口 |
| `token` | string | `""` | 认证 Token（空=不验证） |

示例：

```yaml
coordinator:
  webhook:
    enabled: true
    token: "your-secret-token"  # 推荐设置，防止未授权访问
```

> **使用方式**：`POST /api/webhook`，Header 传 `X-SSUBB-Token`，Body 传 `{"media_path": "/path/to/video.mkv"}`。详见 `/docs` API 文档。

### 阶段超时 (`stage_timeout`)

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `extracting` | int | `600` | 音频提取超时 (秒) |
| `uploading` | int | `600` | 上传超时 (秒) |
| `transcribing` | int | `3600` | 转写超时 (秒) |
| `translating` | int | `1800` | 翻译超时 (秒) |
| `default` | int | `1800` | 默认超时 (秒) |

## Worker 配置项

### 基础

| 配置项 | 类型 | 默认值 | 必填 | 说明 |
|---|---|---|---|---|
| `host` | string | `0.0.0.0` | | 监听地址 |
| `port` | int | `8788` | | 监听端口 |
| `worker_id` | string | `office-gpu` | | 节点标识 |
| `coordinator_url` | string | `""` | ✅ | Coordinator 回调地址 |
| `temp_dir` | string | `./data/worker_temp` | | 临时文件目录 |

### 转写 (`transcribe`)

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `model` | string | `large-v3-turbo` | Whisper 模型 |
| `device` | string | `cuda` | 计算设备 |
| `compute_type` | string | `float16` | 精度类型 |
| `vad_filter` | bool | `true` | VAD 静音过滤 |
| `model_dir` | string | `./models` | 模型缓存目录 |

### LLM (`llm`) — 向后兼容

| 配置项 | 类型 | 默认值 | 必填 | 说明 |
|---|---|---|---|---|
| `api_base` | string | `""` | ✅ | OpenAI 兼容 API 地址 |
| `api_key` | string | `""` | ✅ | API Key |
| `model` | string | `""` | ✅ | 模型名称 |

> **向后兼容**：如果 `llm_providers` 为空但 `llm.api_key` 有值，系统会自动将其迁移为单元素 `llm_providers` 列表。

### LLM 多端点容灾 (`llm_providers`) — V0.10 新增

支持配置多个 LLM 提供商，按优先级自动切换。单点故障不再影响全局。

| 配置项 | 类型 | 默认值 | 必填 | 说明 |
|---|---|---|---|---|
| `api_base` | string | — | ✅ | OpenAI 兼容 API 地址 |
| `api_key` | string | — | ✅ | API Key |
| `model` | string | — | ✅ | 模型名称 |
| `priority` | int | `1` | | 优先级（数字越小越优先） |
| `enabled` | bool | `true` | | 是否启用 |
| `label` | string | `""` | | 可选标签（如 "DeepSeek-主力"） |

示例：

```yaml
worker:
  llm_providers:
    - api_base: "https://api.deepseek.com/v1"
      api_key: "sk-xxx"
      model: "deepseek-chat"
      priority: 1
      label: "DeepSeek-主力"
    - api_base: "https://api.openai.com/v1"
      api_key: "sk-yyy"
      model: "gpt-4o-mini"
      priority: 2
      label: "OpenAI-备用"
    - api_base: "https://open.bigmodel.cn/api/paas/v4"
      api_key: "..."
      model: "glm-4-flash"
      priority: 3
      enabled: false
      label: "智谱-停用"
```

> **配置方式**：推荐在 Coordinator WebUI 的设置面板中配置，Coordinator 会自动推送到所有在线 Worker 并热重载，无需手动编辑 Worker 端的 config.yaml。

### 翻译 (`translate`)

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `service` | string | `llm` | 翻译服务 |
| `target_language` | string | `zh` | 目标语言 |
| `thread_num` | int | `5` | 并发数 |
| `batch_size` | int | `10` | 每批条数 |
| `need_reflect` | bool | `false` | 反思翻译（V0.10 生效：翻译后二次审校） |

### 字幕优化 (`optimize`)

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | bool | `true` | 启用 LLM 断句优化 |
| `max_word_count_cjk` | int | `12` | CJK 每行最大字数（V0.10 生效：LLM 优化时遵守） |
| `max_word_count_english` | int | `18` | 英文每行最大词数（V0.10 生效：LLM 优化时遵守） |

### VRAM 管理 (`vram`)

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `clear_on_complete` | bool | `true` | 完成后清理显存 |
| `cleanup_delay` | int | `30` | 清理延迟 (秒) |

## 最小可运行配置

只需填写以下必填项即可启动：

**单 Worker 模式（向后兼容）：**

```yaml
coordinator:
  worker:
    url: "http://<worker-ip>:8788"

worker:
  coordinator_url: "http://<nas-ip>:8787"
  transcribe:
    device: "cuda"       # 或 cpu
  llm:
    api_base: "https://api.example.com/v1"
    api_key: "your-api-key"
    model: "your-model-name"
```

**多 Worker 模式（V0.6+）：**

```yaml
coordinator:
  workers:
    - url: "http://<worker-1-ip>:8788"
      weight: 2
    - url: "http://<worker-2-ip>:8788"
      weight: 1

worker:
  coordinator_url: "http://<nas-ip>:8787"
  transcribe:
    device: "cuda"
  llm:
    api_base: "https://api.example.com/v1"
    api_key: "your-api-key"
    model: "your-model-name"
```

其余配置项均有合理默认值。
