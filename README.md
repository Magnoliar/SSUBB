# SSUBB — 分布式字幕转写翻译系统

> NAS 自动发现没字幕的影视 → 发到 GPU 机器转写翻译 → 字幕自动写回。全程无需人工干预。

---

## 它能做什么

```
NAS (存储)                    GPU (算力)
┌──────────────┐    音频     ┌──────────────┐
│ 扫描影视库    │  ───────→  │ Whisper 转写  │
│ 提取音频      │            │ LLM 翻译     │
│ 写回字幕      │  ←───────  │ 质量评分     │
│ 通知 Emby     │    字幕     │              │
└──────────────┘            └──────────────┘
```

- 扫描影视库，自动发现缺少中文字幕的视频
- Whisper AI 语音转文字（支持 99 种语言自动检测）
- LLM 翻译成中文（DeepSeek / OpenAI / 智谱等，支持多源容灾）
- 字幕自动写回视频旁，通知 Emby/Jellyfin 刷新
- 支持多 GPU 节点并发、优先级队列、故障自动迁移

---

## 快速开始

### 你需要什么

| 角色 | 设备 | 说明 |
|------|------|------|
| **Coordinator** | NAS 或家用电脑 | 调度中心，不需要 GPU，推荐 Docker 部署 |
| **Worker** | 有 GPU 的电脑 | NVIDIA 显卡 4GB+，首次启动自动下载 faster-whisper-xxl |
| **LLM API** | DeepSeek 等 | 翻译用，一部电影约 ¥0.1 |
| **网络** | 同一局域网 | 或 Tailscale 内网穿透 |

---

### 第一步：NAS 端 — 启动 Coordinator（Docker）

在你的 NAS 或家用电脑上执行：

```bash
# 1. 克隆项目
git clone https://github.com/Magnoliar/SSUBB.git && cd SSUBB

# 2. 生成配置文件
python3 -m coordinator.setup_wizard

# 3. 启动服务
docker compose up -d
```

启动后访问 `http://NAS_IP:8787`，首次启动会自动生成 API Token（显示在终端日志中，WebUI 登录需要）。

**没有 Docker？** 也可以裸机运行：
- Windows：双击 `start_coordinator.bat`
- Linux：`bash start_coordinator.sh`

---

### 第二步：GPU 端 — 启动 Worker

在有 GPU 的电脑上：

> Worker 首次启动会自动下载 **faster-whisper-xxl**（内置 CUDA 运行时，约 200MB），无需手动安装 PyTorch。Whisper 模型也会在首次转写时自动下载（约 3GB）。

启动 Worker：

**二选一**：

**方式 A：下载编译好的 exe（推荐）**

从 [GitHub Releases](https://github.com/Magnoliar/SSUBB/releases) 下载：
- Windows：`ssubb-worker-win64.exe`
- Linux：`ssubb-worker-linux-x64`

双击运行，首次启动会自动引导配置。

**方式 B：从源码运行**

```bash
git clone https://github.com/Magnoliar/SSUBB.git && cd SSUBB

# Windows
worker\run_worker.bat

# Linux
bash worker/run_worker.sh
```

脚本自动安装依赖、检测 GPU/FFmpeg、引导配置。

---

### 第三步：配置连接

Worker 首次启动会弹出配置向导，需要填写：
- **Coordinator 地址**：`http://NAS_IP:8787`
- **Worker Token**：在 Coordinator WebUI 的「设置 → 安全」页面查看
- **LLM API Key**：推荐 [DeepSeek](https://platform.deepseek.com/)（便宜又好用）

配置完成后 Worker 自动注册到 Coordinator，可以在 WebUI 的「看板」页面看到在线状态。

---

### 第四步：测试

打开 `http://NAS_IP:8787` → 看板 → 影视资源列表 → 选择一个没字幕的视频 → 点击「生成字幕」→ 等几分钟 → 字幕出现在视频旁。

---

## 功能一览

### 核心能力
| 功能 | 版本 | 说明 |
|------|------|------|
| 多节点并发 | V0.6+ | 多个 GPU Worker 按权重分配任务 |
| 优先级队列 | V0.8+ | 1-5 级优先级，高优先级优先处理 |
| 故障自动迁移 | V0.8+ | Worker 离线后任务自动转移 |
| MoviePilot 集成 | V0.2+ | 入库自动触发字幕生成 |
| 自动扫描 | V0.2+ | 定时扫描影视库，补齐缺失字幕 |
| 音轨智能选择 | V0.12+ | FFprobe 分析音轨，优先英语音轨 |

### 字幕质量
| 功能 | 版本 | 说明 |
|------|------|------|
| 反思翻译 | V0.10+ | 翻译后二次审校提升质量 |
| 质量评分 | V0.8+ | 0-100 分自动评估，低分自动重试 |
| 术语提取 | V0.11+ | 豆瓣/维基搜索专有名词官方译名 |
| 文化注释 | V0.12+ | 自动生成双关语、典故翻译备注 |
| 智能排版 | V0.4+ | 分片翻译、时轴矫正、ASS 特效 |
| 断句优化 | V0.10+ | 长句防截断，按语言约束行长 |

### 控制台 (WebUI)
| 功能 | 版本 | 说明 |
|------|------|------|
| 侧边栏三 tab | V1.0 | 看板 / 任务 / 配置，URL hash 同步 |
| 影视资源列表 | V1.0 | 扫描媒体库，显示字幕状态，一键生成 |
| 分段进度条 | V1.0 | 阶段色块 + 百分比 + 已耗时 + 预估剩余 |
| 配置统管 | V1.0 | Coordinator 统一管理 LLM/转写/翻译配置 |
| LLM 提供商管理 | V1.0 | 卡片式编辑器，测试连通性，多源容灾 |
| 转写模型选择 | V1.0 | 显示本地下载状态、大小、显存、速度、质量 |
| 字幕预览编辑 | V1.0+ | 在线预览 SRT，手动编辑，AI 优化 |
| 批量操作 | V0.9+ | 勾选后批量重试/取消/删除 |
| 数据洞察 | V0.9+ | 30 天趋势、成功率、Worker 利用率 |

### 安全
| 功能 | 版本 | 说明 |
|------|------|------|
| Token 自动生成 | V1.0 | 首次启动自动生成 API Token + Worker Token |
| 速率限制 | V1.0 | IP 级限流（POST 60/min, PUT 30/min） |
| 路径校验 | V1.0 | media_path 限制在媒体库范围内 |
| CORS 收紧 | V1.0 | 默认仅允许 localhost |
| API Token 鉴权 | V0.11+ | Bearer Token 认证，WebUI 登录 |
| Worker Token | V0.11+ | Worker 回调认证 |

### 通知 & 集成
| 功能 | 版本 | 说明 |
|------|------|------|
| 多渠道通知 | V0.11+ | Bark / PushPlus / Gotify / 通用 Webhook |
| Emby/Jellyfin | V0.1+ | 自动通知刷新媒体库 |
| 通用 Webhook | V0.8+ | `POST /api/webhook` 触发任务 |
| 局域网自动发现 | V0.7+ | UDP 广播自动注册 Worker |

---

## 配置速查

大多数配置可通过 WebUI 设置页面完成，无需手动编辑 YAML。

| 配置项 | 位置 | 说明 |
|--------|------|------|
| `coordinator.workers` | Coordinator WebUI | GPU 节点列表 |
| `coordinator.llm_providers` | Coordinator WebUI | LLM 提供商（支持多个，自动容灾） |
| `coordinator.transcribe` | Coordinator WebUI | 转写模型/设备/精度 |
| `coordinator.security.api_token` | 自动生成 | API 鉴权 Token |
| `worker.coordinator_url` | Worker config | Coordinator 地址 |
| `worker.coordinator_token` | Worker config | Worker Token（与 Coordinator 匹配） |

完整配置说明见 [docs/configuration.md](docs/configuration.md)。

---

## 下载

从 [GitHub Releases](https://github.com/Magnoliar/SSUBB/releases) 下载：

| 文件 | 平台 | 说明 |
|------|------|------|
| `ssubb-worker-*-win64.exe` | Windows | Worker 主程序 |
| `ssubb-worker-*-linux-x64` | Linux | Worker 主程序 |
| `ssubb-launcher-*-win64.exe` | Windows | Worker 桌面启动器（可选） |
| `ssubb-launcher-*-linux-x64` | Linux | Worker 桌面启动器（可选） |

**Worker** 是核心程序，负责转写翻译。命令行运行，接收任务、调用 faster-whisper-xxl + LLM。首次启动自动下载转写引擎。

**Launcher** 是可选的桌面 GUI，提供：
- 环境检测（GPU / CUDA / FFmpeg / 模型）
- 一键启动/停止/重启 Worker
- 实时日志查看
- 配置编辑（不用手写 YAML）
- 系统托盘常驻

> **无需手动安装 PyTorch**：Worker 使用 faster-whisper-xxl 独立二进制（内置 CUDA 运行时），首次启动自动下载。

---

## 技术栈

- **后端**：Python 3.10+ / FastAPI / SQLite / asyncio
- **前端**：Vue 3 + Tailwind CSS（单文件 SPA，无构建工具）
- **转写**：faster-whisper-xxl 独立二进制（内置 CUDA，无需 PyTorch）
- **翻译**：OpenAI 兼容 API（DeepSeek / GPT / 智谱等）
- **部署**：Docker Compose / 裸机脚本 / 预编译 exe

```
coordinator/          NAS 端（任务调度 + WebUI + 字幕写入）
  ├── main.py         FastAPI 入口，39 个 API 端点
  ├── config.py       Pydantic 配置模型（21 字段）
  ├── task_manager.py 任务生命周期管理
  ├── scanner.py      影视库扫描
  └── static/index.html  190KB 单文件 SPA

worker/               GPU 端（转写 + 翻译）
  ├── main.py         Worker API 服务
  ├── task_executor.py 转写 + 翻译执行器
  └── translator.py   LLM 翻译（多源容灾）

shared/               共用数据模型与常量
launcher/             PySide6 桌面启动器（11 个模块）
moviepilot-plugin/    MoviePilot 自动触发插件
```

---

## 版本进度

| 版本 | 状态 | 核心内容 |
|------|------|----------|
| V0.1~V0.5 | ✅ 完成 | 核心链路、容错、自动化、WebUI、Docker |
| V0.6~V0.7 | ✅ 完成 | 多节点并发、自动发现、WebUI 体验升级 |
| V0.8~V0.9 | ✅ 完成 | 智能调度、Webhook、批量操作、数据洞察 |
| V0.10~V0.12 | ✅ 完成 | LLM 容灾、字幕编辑、术语提取、注释系统 |
| V1.0 | ✅ 发布 | WebUI 重构 + 配置统管 + 安全加固 + exe 打包 + 桌面启动器 |
| **V1.1** | **✅ 发布** | 消除 PyTorch 依赖，改用 faster-whisper-xxl 独立二进制，自动下载安装 |

---

## 已知限制

1. **单卡串行**：每个 Worker 串行处理（多 Worker 可并发）
2. **大文件耗时**：50GB+ 蓝光原盘受带宽和 I/O 限制
3. **小众语言**：方言或极端噪音下 Whisper 可能幻听
4. **内网优先**：建议不要直接暴露公网，搭配 Tailscale 或 Nginx

---

## 常见问题

**Q: 两台机器不在同一网络？** → 用 [Tailscale](https://tailscale.com/)（免费）

**Q: 没有 GPU？** → 能用，但转写慢 10 倍+。建议 GTX 1060 以上。

**Q: 一部电影多久？** → RTX 3060 参考：90 分钟电影转写 3~5 分钟，翻译 1~2 分钟。

**Q: 字幕质量？** → large-v3-turbo + DeepSeek 超过大部分网上下载字幕。开启 `need_reflect: true` 可进一步提升。

**Q: Worker exe 闪退？** → 首次启动会自动下载 faster-whisper-xxl（约 200MB），请确保网络通畅。如果自动下载失败，可从 [这里](https://github.com/Purfview/whisper-standalone-win/releases) 手动下载并放到 `./bin/` 目录。

**Q: Coordinator 怎么更新？** → `docker compose pull && docker compose up -d`（Docker）或 `git pull`（裸机）

---

## 开发方式

纯 **AI 结对编程** 驱动开发。后端 FastAPI 高并发异步调度，前端 Vue 3 + TailwindCSS 极简控制台。

---

## 致谢

- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper)：语音转写基础
- [MoviePilot](https://github.com/jxxghp/MoviePilot)：自动化媒体库管理
- [subgen](https://github.com/McCloudS/subgen)：分布式字幕工作流灵感
- [VideoCaptioner](https://github.com/WEIFENG2333/VideoCaptioner)：分片翻译防截断思路
- DeepSeek / 智谱等：让高质量 AI 翻译廉价可及

---

## License

MIT License。详见 [LICENSE](LICENSE)。

> **免责声明**：仅供学习与技术交流，AI 翻译存在不可控性，开发者不对生成字幕的准确性负责。

---

## 遇到问题？

1. 查看 WebUI 实时日志（`http://NAS_IP:8787`）
2. 检查 Worker 终端输出
3. 大部分问题是网络不通或配置填错
