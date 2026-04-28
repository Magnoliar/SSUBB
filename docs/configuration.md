# SSUBB 配置手册

## 快速开始

```bash
# 1. 复制示例配置
cp config.example.yaml config.yaml

# 2. 编辑必填项
#    - coordinator.worker.url
#    - worker.coordinator_url
#    - worker.llm.api_base / api_key / model
```

## 配置优先级

SSUBB 的配置加载遵循以下优先级（高 → 低）：

1. **环境变量** (`SSUBB_*`)
2. **config.yaml** 中的值
3. **代码默认值**

## 环境变量一览

| 环境变量 | 对应配置项 | 说明 |
|---|---|---|
| `SSUBB_CONFIG` | — | 配置文件路径 (默认 `./config.yaml`) |
| `SSUBB_WORKER_URL` | `coordinator.worker.url` | Worker 地址 |
| `SSUBB_EMBY_SERVER` | `coordinator.emby.server` | Emby 地址 |
| `SSUBB_EMBY_API_KEY` | `coordinator.emby.api_key` | Emby API Key |
| `SSUBB_DB_PATH` | `coordinator.db_path` | 数据库路径 |
| `SSUBB_COORDINATOR_URL` | `worker.coordinator_url` | Coordinator 回调地址 |
| `SSUBB_WORKER_ID` | `worker.worker_id` | Worker 节点 ID |
| `SSUBB_LLM_API_BASE` | `worker.llm.api_base` | LLM API 地址 |
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

### Worker 连接 (`worker`)

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

### LLM (`llm`)

| 配置项 | 类型 | 默认值 | 必填 | 说明 |
|---|---|---|---|---|
| `api_base` | string | `""` | ✅ | OpenAI 兼容 API 地址 |
| `api_key` | string | `""` | ✅ | API Key |
| `model` | string | `""` | ✅ | 模型名称 |

### 翻译 (`translate`)

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `service` | string | `llm` | 翻译服务 |
| `target_language` | string | `zh` | 目标语言 |
| `thread_num` | int | `5` | 并发数 |
| `batch_size` | int | `10` | 每批条数 |
| `need_reflect` | bool | `false` | 反思翻译 |

### 字幕优化 (`optimize`)

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | bool | `true` | 启用 LLM 断句优化 |
| `max_word_count_cjk` | int | `12` | CJK 每行最大字数 |
| `max_word_count_english` | int | `18` | 英文每行最大词数 |

### VRAM 管理 (`vram`)

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `clear_on_complete` | bool | `true` | 完成后清理显存 |
| `cleanup_delay` | int | `30` | 清理延迟 (秒) |

## 最小可运行配置

只需填写以下必填项即可启动：

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

其余配置项均有合理默认值。
