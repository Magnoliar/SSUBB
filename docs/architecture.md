# SSUBB 项目架构

## 1. 设计目标

SSUBB 面向的是“媒体库在家里，算力在异地”的字幕处理场景。

典型前提：

- NAS 挂着 Emby / MoviePilot，保存最终视频和字幕。
- 公司电脑 24 小时开机，带 NVIDIA GPU，适合跑 Whisper 和 LLM。
- 两端可以通过 Tailscale、ZeroTier、VPN 或固定公网地址互联。

设计目标有三个：

1. 让 NAS 只承担轻任务。
2. 让 GPU 机器只承担重任务。
3. 字幕结果最终仍然回到媒体库本地，兼容现有观影工作流。

## 2. 逻辑分层

### 2.1 接入层

入口有三种：

- MoviePilot 插件自动触发
- Emby webhook 触发
- WebUI / API 手动触发

这一层只负责“把媒体文件变成任务请求”。

### 2.2 编排层

`Coordinator` 是整个系统的大脑，负责：

- 任务去重
- 字幕存在性和质量检查
- 音频提取
- 上传 Worker
- 接收回调
- 写回字幕
- 刷新 Emby

这里也是项目最适合继续扩展的地方，例如后续做多 Worker、重试策略、任务优先级，基本都落在这一层。

### 2.3 执行层

`Worker` 是纯计算节点，负责：

- 接收音频分块
- 合并音频
- 调用 ASR 模型
- 调用 LLM 做优化和翻译
- 回调结果

它的目标是尽量“无状态”。现在虽然还有临时目录和队列，但总体方向是对的。

从中长期演进看，`Worker` 不一定只是一段后台服务，它也可以继续封装成“客户端节点”：

- 外部是桌面启动器或 launcher
- 内部仍然是当前 Worker 服务内核
- 启动器负责环境检测、模型下载、配置引导和服务拉起

这样会更符合“异地算力节点”的实际使用场景。

### 2.4 存储层

当前主要存储包括：

- `SQLite`: 任务状态和历史记录
- `data/audio_temp`: Coordinator 抽取的临时音频
- `data/worker_temp`: Worker 合并音频后的临时文件
- 媒体目录中的 `.srt`: 最终产物

## 3. 节点拓扑

```mermaid
flowchart TD
    subgraph Home["家庭网络"]
        MP["MoviePilot"]
        EMBY["Emby"]
        NAS["Coordinator / NAS"]
        DB["SQLite + Logs"]
        MEDIA["Media Library"]
        MP --> NAS
        EMBY --> NAS
        NAS --> DB
        NAS --> MEDIA
    end

    subgraph Office["公司网络"]
        GPU["Worker / Windows + 4070 Ti Super"]
        MODEL["Whisper / LLM / CUDA"]
        GPU --> MODEL
    end

    NAS <-->|"HTTP / 分块上传 / 回调"| GPU
```

## 4. 时序流程

```mermaid
sequenceDiagram
    participant MP as MoviePilot / 手动请求
    participant C as Coordinator
    participant W as Worker
    participant E as Emby

    MP->>C: 创建任务
    C->>C: 去重 + 字幕检查
    C->>C: FFmpeg 抽取音频
    C->>W: 分块上传音频
    W->>W: 合并 + Hash 校验
    W->>W: 转写 / 优化 / 翻译
    W->>C: 回调字幕结果
    C->>C: 写回 .srt
    C->>E: 刷新媒体元数据
```

## 5. 模块职责拆解

### 5.1 `coordinator/`

核心模块：

- `main.py`: FastAPI 入口、API 暴露、WebUI 挂载
- `task_manager.py`: 任务生命周期和主流程编排
- `task_store.py`: SQLite 持久化
- `audio_extractor.py`: FFmpeg 抽音频
- `subtitle_checker.py`: 检测已有字幕是否可复用
- `subtitle_writer.py`: 写回字幕并刷新 Emby
- `worker_client.py`: 上传 Worker、查询状态

适合继续演进的方向：

- 多 Worker 调度
- 更严格的状态机
- 更清晰的重试与恢复

### 5.2 `worker/`

核心模块：

- `main.py`: FastAPI 入口、分块接收、队列处理
- `task_executor.py`: 转写、优化、翻译主链路
- `llm_client.py`: LLM 调用封装
- `optimizer.py`: 字幕优化
- `translator.py`: 字幕翻译
- `health.py`: Worker 健康状态

适合继续演进的方向：

- 队列优先级
- 取消任务
- 模型常驻与复用
- 更细粒度的进度上报
- 客户端化封装，提供更低门槛的部署和迁移体验

### 5.4 `worker-launcher/`（未来方向）

如果后续推进 Worker 客户端化，建议单独引入一个 `worker-launcher/` 或类似模块，作为桌面启动器层。

建议职责：

- 启动前环境检查
- CUDA / 显卡 / 端口 / 网络状态检测
- 模型下载、校验和缓存目录管理
- Worker 配置初始化与升级
- 启动、停止、重启 Worker 服务
- 展示基础状态、日志和错误提示

这样可以把“部署体验”与“计算内核”解耦，避免把所有 UI / 启动逻辑直接塞进当前 Worker 服务里。

### 5.3 `moviepilot-plugin/`

定位：

- 不是核心处理节点，而是自动化入口适配层。
- 把 MoviePilot 的媒体事件翻译成 SSUBB 任务请求。
- 接收结果回调，并向 MoviePilot 发通知。

## 6. 状态机建议

当前代码里已经有这些状态：

- `pending`
- `extracting`
- `uploading`
- `transcribing`
- `optimizing`
- `translating`
- `aligning`
- `completed`
- `failed`
- `skipped`
- `cancelled`

从架构角度，后续建议把它明确分为四个阶段：

1. Coordinator 本地阶段
2. 传输阶段
3. Worker 执行阶段
4. 回收阶段

这样好处是：

- 更容易判断任务到底卡在哪一段
- 更容易做重试策略
- 更容易做 UI 展示和统计

## 7. 当前版本 (V0.5) 架构亮点

### 7.1 WebUI 与零配置驱动
在 V0.5 中，**彻底淘汰了强迫新手修改 YAML 的部署方式**：
- **NAS 端 (Coordinator)**：如果在 Docker 启动时未提供配置文件，系统会进入 `SETUP_REQUIRED` 模式。用户访问 WebUI 时会自动跳转至一个类似 WordPress 安装的网页交互向导，在网页中填入参数后，引擎将在内存中直接热启动。
- **GPU 端 (Worker)**：启动脚本 (`run_worker.bat/sh`) 会自动引导环境检测（CUDA/FFmpeg）、交互式请求 LLM API Key，并在后台自动拉取 Whisper 模型，实现双端真正的开箱即用。

### 7.2 健壮的重试与恢复机制
- **细粒度超时**：不同阶段具有独立的超时重置（例如，翻译阶段为半小时，转写阶段为一小时）。
- **任务防重**：同一物理文件的重复请求将被 Coordinator 在入口处直接拦截，有效防止重复计算资源的浪费。

## 8. 未来演进路线

SSUBB 现在的核心价值，是它将家庭环境抽象成了一个明确且高度解耦的架构：
- **NAS**：保存核心资产和接管前端交互。
- **异地 Worker**：承接重型 AI 算力。
- **HTTP/JSON**：两者之间通过简单稳定的短连接协议解耦。

接下来，架构上最适合继续推进的点在于：
1. **多 Worker 并发调度**：将点对点升级为一对多，Coordinator 记录不同 Worker 的算力权重（如 4090 vs 3060），实现负载均衡。
2. **重叠流水线 (Pipelining)**：打破单节点串行，让 NAS 在抽 B 视频音频的同时，GPU A 正在转写 A 视频，LLM 在翻译更早之前的请求，实现吞吐量最大化。
