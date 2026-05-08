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
| **Worker** | 有 GPU 的电脑 | NVIDIA 显卡 4GB+，首次启动自动下载转写引擎 |
| **LLM API** | DeepSeek 等 | 翻译用，一部电影约 ¥0.1 |
| **网络** | 同一局域网 | 或 Tailscale 内网穿透 |

---

### 第一步：NAS 端 — 启动 Coordinator

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

在有 GPU 的电脑上，从 [GitHub Releases](https://github.com/Magnoliar/SSUBB/releases) 下载对应平台的 Worker 可执行文件，双击运行即可。

首次启动会自动：
1. 下载 **faster-whisper-xxl** 转写引擎（约 200MB，内置 CUDA 运行时）
2. 弹出配置向导，引导填写 Coordinator 地址和 LLM API Key
3. Whisper 模型会在首次转写任务时自动下载（约 3GB）

> **无需手动安装 PyTorch 或 CUDA**：faster-whisper-xxl 是独立二进制，自带 CUDA 运行时。

也可以从源码运行：

```bash
git clone https://github.com/Magnoliar/SSUBB.git && cd SSUBB

# Windows
worker\run_worker.bat

# Linux
bash worker/run_worker.sh
```

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

### 转写 & 翻译
- **faster-whisper-xxl** 独立二进制转写，内置 CUDA，无需 PyTorch
- **多语言自动检测**：99 种语言，Whisper 自动识别
- **LLM 多源容灾**：DeepSeek / OpenAI / 智谱等多提供商按优先级自动切换
- **反思翻译**：翻译后可选二次审校，提升质量
- **术语提取**：豆瓣/维基搜索专有名词官方译名，确保翻译一致
- **文化注释**：自动生成双关语、典故翻译备注
- **质量评分**：0-100 分自动评估，低分自动重试

### 调度 & 可靠性
- **多节点并发**：多个 GPU Worker 按权重分配任务
- **优先级队列**：1-5 级优先级，高优先级优先处理
- **故障自动迁移**：Worker 离线后任务自动转移到其他节点
- **局域网自动发现**：UDP 广播，Worker 自动注册，免填 IP
- **MoviePilot 集成**：入库自动触发字幕生成

### 控制台 (WebUI)
- **侧边栏三 tab**：看板 / 任务 / 配置，URL hash 同步
- **影视资源列表**：扫描媒体库，显示字幕状态，一键生成
- **分段进度条**：阶段色块 + 百分比 + 已耗时 + 预估剩余
- **字幕预览编辑**：在线预览 SRT，手动编辑，AI 优化
- **配置统管**：Coordinator 统一管理 LLM/转写/翻译配置，自动推送到 Worker
- **数据洞察**：30 天趋势、成功率、Worker 利用率

### 安全
- 首次启动自动生成 API Token + Worker Token
- IP 级速率限制（POST 60/min, PUT 30/min）
- media_path 路径校验防止越权访问
- CORS 默认收紧为 localhost

### 通知
- 多渠道 Webhook：Bark / PushPlus / Gotify / 通用
- Emby / Jellyfin 自动通知刷新媒体库

---

## 下载

从 [GitHub Releases](https://github.com/Magnoliar/SSUBB/releases) 下载：

| 文件 | 平台 | 说明 |
|------|------|------|
| `ssubb-worker-*-win64.exe` | Windows | Worker 主程序（转写 + 翻译） |
| `ssubb-worker-*-linux-x64` | Linux | Worker 主程序 |
| `ssubb-launcher-*-win64.exe` | Windows | Worker 桌面启动器（可选） |
| `ssubb-launcher-*-linux-x64` | Linux | Worker 桌面启动器（可选） |

**Worker** 是核心程序，负责转写翻译。命令行运行，接收任务、调用 faster-whisper-xxl + LLM。

**Launcher** 是可选的桌面 GUI，提供环境检测、一键启停、实时日志、配置编辑、系统托盘。

---

## 技术栈

- **后端**：Python 3.10+ / FastAPI / SQLite / asyncio
- **前端**：Vue 3 + Tailwind CSS（单文件 SPA，无构建工具）
- **转写**：faster-whisper-xxl 独立二进制（内置 CUDA，无需 PyTorch）
- **翻译**：OpenAI 兼容 API（DeepSeek / GPT / 智谱等）
- **部署**：Docker Compose / 裸机脚本 / 预编译 exe

---

## 版本历史

| 版本 | 核心内容 |
|------|----------|
| V0.1~V0.5 | 核心链路、容错、自动化、WebUI、Docker |
| V0.6~V0.7 | 多节点并发、自动发现、WebUI 体验升级 |
| V0.8~V0.9 | 智能调度、Webhook、批量操作、数据洞察 |
| V0.10~V0.12 | LLM 容灾、字幕编辑、术语提取、注释系统 |
| V1.0 | WebUI 重构 + 配置统管 + 安全加固 + exe 打包 + 桌面启动器 |
| V1.1 | 消除 PyTorch 依赖，改用 faster-whisper-xxl 独立二进制 |
| V1.2 | 全面审计修复 + GUI 修复 + CI 简化 |

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

**Q: Worker exe 闪退？** → 首次启动会自动下载 faster-whisper-xxl（约 200MB），请确保网络通畅。如果自动下载失败，可从 [这里](https://github.com/Purfview/whisper-standalone-win/releases) 手动下载并放到 exe 同目录的 `bin/` 文件夹。

**Q: Coordinator 怎么更新？** → `docker compose pull && docker compose up -d`（Docker）或 `git pull`（裸机）

---

## 开发方式

纯 **AI 结对编程** 驱动开发。后端 FastAPI 高并发异步调度，前端 Vue 3 + TailwindCSS 极简控制台。

---

## 致谢

- [Faster-Whisper-XXL](https://github.com/Purfview/whisper-standalone-win)：独立转写二进制
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
