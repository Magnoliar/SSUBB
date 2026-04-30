# SSUBB 配置手册 (V0.11)

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
| `SSUBB_API_TOKEN` | `coordinator.security.api_token` | Coordinator API 鉴权 Token (V0.11) |
| `SSUBB_WORKER_TOKEN` | `coordinator.security.worker_token` | Worker 回调认证 Token (V0.11) |

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
| `output_mode` | string | `single` | 输出模式 (`single` / `bilingual`) |
| `output_format` | string | `srt` | 输出格式 (`srt` / `ass`) |

### ASS 样式 (`subtitle.ass_style`) — V0.11 新增

单语 ASS 字幕的样式配置。仅在 `output_format: ass` 时生效。

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `font_name` | string | `Noto Sans` | 字体名称 |
| `font_size` | int | `12` | 字体大小 |
| `primary_colour` | string | `&H00FFFFFF` | 主颜色（ASS 格式） |
| `outline_colour` | string | `&H000000FF` | 边框颜色 |
| `back_colour` | string | `&H80000000` | 阴影颜色 |
| `bold` | int | `-1` | 粗体 (-1=是, 0=否) |
| `outline_width` | float | `1.5` | 边框宽度 |
| `shadow` | int | `0` | 阴影深度 |
| `alignment` | int | `2` | 对齐 (1-9, 2=底部居中) |
| `margin_l` | int | `10` | 左边距 |
| `margin_r` | int | `10` | 右边距 |
| `margin_v` | int | `30` | 底部边距 |
| `play_res_x` | int | `1920` | 播放分辨率 X |
| `play_res_y` | int | `1080` | 播放分辨率 Y |

### ASS 双语样式 (`subtitle.ass_bilingual_style`) — V0.11 新增

双语模式下原文（顶部）的样式。翻译始终使用 `Default` 样式。

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `font_size` | int | `10` | 原文字体大小（比译文小） |
| `alignment` | int | `8` | 对齐 (8=顶部居中) |
| `margin_v` | int | `10` | 顶部边距 |

### 安全认证 (`security`) — V0.11 新增

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `api_token` | string | `""` | Coordinator API 鉴权 Token（空=不验证） |
| `worker_token` | string | `""` | Worker 回调认证 Token（空=不验证） |
| `cors_origins` | list | `["*"]` | CORS 允许的来源列表 |

示例：

```yaml
coordinator:
  security:
    api_token: "your-secret-api-token"
    worker_token: "your-worker-token"
    cors_origins:
      - "http://localhost:8787"
      - "http://192.168.1.10:8787"
```

> **安全建议**：生产环境务必设置 `api_token`，防止未授权访问。WebUI 登录后 token 存储在 localStorage。Worker 回调时需携带 `worker_token`，Coordinator 通过 `verify_worker_token` 中间件校验。可通过 `SSUBB_API_TOKEN` 和 `SSUBB_WORKER_TOKEN` 环境变量注入。

### 通知系统 (`notifications`) — V0.11 新增

任务完成/失败时通过 Webhook 推送通知。支持多渠道（Bark/PushPlus/Gotify/通用 Webhook）。

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | bool | `false` | 是否启用通知 |
| `channels` | list | `[]` | 通知渠道列表 |

每个渠道的配置：

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `name` | string | — | 渠道名称（如 "Bark-手机"） |
| `url` | string | — | Webhook URL |
| `enabled` | bool | `true` | 是否启用该渠道 |
| `events` | list | — | 监听的事件类型（`task_completed`, `task_failed`） |
| `headers` | dict | `{}` | 自定义 HTTP 请求头 |
| `template` | string | `""` | 自定义消息模板（空=使用默认模板） |
| `channel_type` | string | `generic` | 渠道类型：`generic`, `bark`, `pushplus`, `gotify` |

示例：

```yaml
coordinator:
  notifications:
    enabled: true
    channels:
      - name: "Bark-手机"
        url: "https://api.day.app/YOUR_KEY"
        events: ["task_completed", "task_failed"]
        channel_type: "bark"
      - name: "PushPlus"
        url: "https://www.pushplus.plus/send"
        events: ["task_failed"]
        channel_type: "pushplus"
```

> **WebUI 测试**：配置保存后可在 WebUI 通知设置面板点击"发送测试"验证连通性。`POST /api/notifications/test` 端点发送测试消息。

### 日志配置 (`logging`) — V0.11 新增

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `level` | string | `INFO` | 日志级别 (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `max_size_mb` | int | `10` | 单个日志文件最大大小 (MB) |
| `backup_count` | int | `5` | 日志备份数量 |
| `log_dir` | string | `./data` | 日志文件目录 |

示例：

```yaml
coordinator:
  logging:
    level: "INFO"
    max_size_mb: 20
    backup_count: 3
    log_dir: "./data"
```

> **日志轮转**：使用 `RotatingFileHandler`，当日志文件达到 `max_size_mb` 时自动轮转，保留 `backup_count` 个备份。Coordinator 日志文件名 `ssubb.log`，Worker 日志文件名 `worker.log`。

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
| `enabled` | bool | `false` | 是否启用自动扫描 |
| `scan_paths` | list | `[]` | 扫描目录列表（留空则扫描全部媒体库） |
| `scan_recursive` | bool | `true` | 是否递归扫描子目录 |
| `scan_recent_days` | int | `7` | 只扫描最近 N 天修改的文件 |
| `schedule_start` | string | `02:00` | 调度窗口开始时间 |
| `schedule_end` | string | `06:00` | 调度窗口结束时间 |
| `scan_interval` | int | `30` | 扫描间隔 (秒) |
| `max_tasks_per_scan` | int | `5` | 每次扫描最多提交任务数 |
| `require_worker_idle` | bool | `true` | 仅在 Worker 空闲时触发扫描 |
| `preheat_next_episode` | bool | `true` | 当前任务完成后自动预热下一集 |
| `timezone` | string | `Asia/Shanghai` | 调度时区 (V0.9 新增) |

示例：

```yaml
coordinator:
  automation:
    enabled: true
    scan_paths:
      - "/media/movies"
      - "/media/tv"
    scan_interval: 30
    schedule_start: "02:00"
    schedule_end: "06:00"
    max_tasks_per_scan: 5
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
| `concurrent_transcriptions` | int | `1` | 并发转写数 |
| `vad_filter` | bool | `true` | VAD 静音过滤 |
| `vad_method` | string | `silero_v4_fw` | VAD 方法 |
| `vad_threshold` | float | `0.5` | VAD 检测阈值 |
| `custom_regroup` | string | `cm_sl=84_sl=42++++++1` | 自定义 regroup 策略 |
| `detect_language_length` | int | `30` | 语言检测采样长度（段落） |
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

### 术语提取 (任务级参数) — V0.11 新增

术语提取在翻译前自动运行，从 SRT 字幕中提取专有名词，再通过豆瓣/维基百科搜索官方译名。

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `terminology_enabled` | bool | `true` | 是否启用自动术语提取 |
| `glossary` | dict | `{}` | 手动传入的术语表（跳过自动提取） |
| `media_title` | string | `""` | 媒体标题（用于网络搜索官方译名） |

> **两阶段提取**：第一阶段从 SRT 文本中用 LLM 提取专有名词（基线），第二阶段通过豆瓣电影页面和中文维基百科搜索官方/公认译名（高优先级覆盖）。网络搜索失败时回退到第一阶段结果。术语表注入翻译 Prompt，确保人名、地名、技能名等一致翻译。

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
