# 🎬 SSUBB — 看片自动补字幕

> **一句话说明**：家里 NAS 自动发现没字幕的电影/电视剧 → 发到公司 GPU 转写翻译 → 字幕自动写回 Emby。

---

## 这个项目能干什么？

你有一台 **NAS**（或任何能跑 Python 的家用机），又有一台 **有 GPU 的电脑**（公司的、云服务器、或者你自己的游戏电脑）。

SSUBB 会：
1. 🔍 扫描你的影视库，找到没有中文字幕的视频
2. 🎵 提取音频，上传到 GPU 机器
3. 🗣️ 用 Whisper AI 把语音转成文字
4. 🌐 用大模型（DeepSeek / GPT 等）翻译成中文
5. 📝 自动把字幕文件写回到视频旁边
6. 📺 通知 Emby/Jellyfin 刷新，打开就能看

**全程自动，你不用做任何操作。**

---

## ⚡ 快速开始（5 分钟上手）

### 你需要准备的东西

| 东西 | 说明 |
|---|---|
| **家用机/NAS** | 能跑 Python 3.10+，有 FFmpeg，不需要 GPU |
| **GPU 机器** | 有 NVIDIA 显卡（4GB+ 显存），装了 Python 和 CUDA |
| **LLM API Key** | 推荐 [DeepSeek](https://platform.deepseek.com/)，便宜好用（翻译一部电影约 ¥0.1） |
| **两台机器能互相访问** | 在同一个局域网，或者通过内网穿透/Tailscale 连通 |

---

### 第一步：在 NAS 上启动 Coordinator（推荐用 Docker）

Coordinator 是管理任务的大脑，适合部署在 NAS 上。

**方式一：Docker 部署（强烈推荐，适合群晖/威联通/Unraid）**

```bash
# 1. 下载项目
git clone https://github.com/你的仓库/SSUBB.git
cd SSUBB

# 2. 运行配置向导，它会问你几个简单问题，自动生成 config.yaml
# 如果你的机器没有 python，也可以手动把 config.minimal.yaml 复制成 config.yaml 填一下
python3 -m coordinator.setup_wizard

# 3. 启动
docker compose up -d
```
*提示：打开 `docker-compose.yml`，把里面的 `/volume1/media:/media` 改成你实际的影视库路径。*

**方式二：直接运行（适合 Windows/裸机 Linux）**

- **Windows 用户**：双击 `start_coordinator.bat`
- **Linux/Mac 用户**：运行 `bash start_coordinator.sh`

> 脚本会**自动弹出一个向导**，你只需跟着提示输入 Worker 的 IP，然后一路回车就行，不用自己改复杂的配置文件！

完成后，打开浏览器访问 `http://NAS的IP:8787`，看到控制台就成功了！🎉

---

### 第二步：在 GPU 机器上启动 Worker

```bash
# 下载项目（和 NAS 端一样的代码）
git clone https://github.com/你的仓库/SSUBB.git
cd SSUBB

# 首次启动会自动引导你配置
# Windows:
worker\run_worker.bat

# Linux/Mac:
bash worker/run_worker.sh
```

启动脚本会自动：
1. ✅ 安装 Python 依赖
2. ✅ 检查 GPU / FFmpeg 等环境
3. ✅ 引导你填写配置（NAS 地址、LLM API Key 等）
4. ✅ 下载 Whisper 模型（约 1.6 GB，首次需要等一会）
5. ✅ 启动 Worker 服务

> **没有 GPU？** 也能用，只是转写会很慢。配置向导会自动检测并切换到 CPU 模式。

> **多台 GPU？** V0.6 起支持多 Worker 并发。在 NAS 端的 `config.yaml` 中配置 `workers` 列表即可，Coordinator 会自动按权重分配任务。详见 [配置手册](docs/configuration.md)。

> **懒得填 IP？** V0.7 起支持局域网自动发现。Worker 启动后会自动广播自身信息，Coordinator 收到后自动注册，无需手动填写 IP 地址。

> **要接入其他系统？** V0.8 起支持通用 Webhook。发送 `POST /api/webhook` 即可创建任务，详见 `/docs` API 文档。

> **批量管理？** V0.9 起支持批量重试/取消/删除任务。任务列表勾选后一键操作，还有数据洞察面板查看历史趋势和 Worker 利用率。

> **LLM 容灾？** V0.10 起支持配置多个 LLM 提供商（DeepSeek/OpenAI/智谱等），按优先级自动切换，单点故障不再影响全局。

> **字幕可编辑？** V0.10 起完成任务后可在 WebUI 预览、编辑字幕，还能勾选段落重新调用 AI 优化。

---

### 第三步：测试一下

1. 打开 NAS 端控制台 `http://NAS的IP:8787`
2. 点击「选择文件」→ 找到一个没有中文字幕的视频
3. 点击「提交任务」
4. 等几分钟，字幕就自动出现在视频旁边了！

---

## 📋 配置速查

你**只需要关心这几项**（其他全部用默认值）：

| 配置项 | 在哪里填 | 说明 |
|---|---|---|
| `coordinator.workers` | NAS 端 config.yaml | GPU 节点列表（支持多个），如 `[{url: "http://192.168.1.50:8788"}]` |
| `worker.coordinator_url` | GPU 端 config.yaml | NAS 地址，如 `http://192.168.1.10:8787` |
| `worker.llm.api_base` | GPU 端 config.yaml | LLM API 地址，如 `https://api.deepseek.com/v1` |
| `worker.llm.api_key` | GPU 端 config.yaml | 你的 LLM API Key |
| `worker.llm.model` | GPU 端 config.yaml | 模型名称，如 `deepseek-chat` |

> 💡 **小贴士**：如果你用 `run_worker.bat` 或 `run_worker.sh` 首次启动 Worker，配置向导会一步步问你这些信息，**不需要手动编辑 YAML 文件**。

---

## 🔌 搭配 MoviePilot 使用（全自动模式）

如果你用 [MoviePilot](https://github.com/jxxghp/MoviePilot) 管理下载和入库：

1. 把 `moviepilot-plugin/ssubb` 文件夹复制到 MoviePilot 的插件目录
2. 在 MoviePilot → 插件 → SSUBB 字幕转写 → 设置中填写 Coordinator 地址
3. 打开「入库自动触发」开关

之后每次 MoviePilot 下载入库新影片，就会**自动通知 SSUBB 生成字幕**。

---

## ❓ 常见问题

### Q: 两台机器不在同一个网络怎么办？

推荐用 [Tailscale](https://tailscale.com/)（免费），装上后两台机器就像在同一个局域网，填 Tailscale 分配的 IP 即可。

### Q: 没有 NVIDIA 显卡能用吗？

能用，但转写会非常慢（可能 10 倍以上）。建议至少 GTX 1060 / RTX 3050 以上。

### Q: LLM API Key 怎么获取？

- **DeepSeek**（推荐）：去 [platform.deepseek.com](https://platform.deepseek.com/) 注册，充值 10 元能用很久
- **OpenAI**：去 [platform.openai.com](https://platform.openai.com/) 注册
- **其他兼容的**：任何 OpenAI 兼容 API 都行（如 GLM-4、通义千问等）

### Q: 一部电影大概多久？

取决于片长和 GPU 性能。参考值（RTX 3060）：
- 90 分钟电影 → 转写约 3~5 分钟，翻译约 1~2 分钟
- 45 分钟剧集 → 转写约 1~3 分钟，翻译约 1 分钟

### Q: 支持什么语言？

源语言：Whisper 支持 99 种语言，会自动检测。
目标语言：中文（默认）、英文、日语、韩语、法语、德语等。

### Q: 字幕质量怎么样？

Whisper large-v3-turbo + DeepSeek 翻译的质量已经**超过大部分网上下载的字幕**。
如果想要更高质量，可以开启「反思翻译」（config.yaml 里 `need_reflect: true`）。

---

## 📚 详细文档与项目结构

更多进阶用法和底层架构原理，请参考 `docs/` 目录下的相关文档：

- [架构设计 (architecture.md)](docs/architecture.md)：SSUBB 是如何分离算力与存储的？
- [配置详解 (configuration.md)](docs/configuration.md)：YAML 文件中所有高级参数的详细说明。
- [开发路线 (roadmap.md)](docs/roadmap.md)：项目的历史演进与未来功能计划。
- **API 文档**：Coordinator 启动后访问 `http://<NAS_IP>:8787/docs` 查看完整 REST API。

项目代码结构（供开发者参考）：
- `coordinator/`：NAS 端（任务调度 + WebUI + 字幕写入）
- `worker/`：GPU 端（语音转写 + AI 翻译）
- `shared/`：两端共用的数据模型与常量
- `moviepilot-plugin/`：MoviePilot V2 专用自动触发插件

---

## 🚧 已知边界与限制

在当前版本中，系统仍有一些物理与架构层面的限制，请在使用前知悉：
1. **单卡串行处理**：每个 Worker 端为了保证显存不溢出，任务排队串行处理。但 V0.6 起支持多 Worker 并发，不同节点可同时处理不同任务，配合流水线调度可显著提升吞吐量。
2. **超大原盘耗时**：对于 50GB 甚至 100GB 的超大蓝光原盘，第一步“提取音频”和“网络回传”可能会受到局域网带宽和机械硬盘 I/O 的极大限制而耗时较久。
3. **小众语言混叠**：对于方言、极端冷门语种或背景噪音极大的视频，Whisper 可能会出现幻听（可通过自行更换更大参数模型缓解）。
4. **纯内网分发**：V0.8 起支持 Webhook Token 认证，V0.9 增加了路径遍历防护和配置并发锁，但仍建议**不要将其直接暴露在公网**，搭配局域网、Tailscale 或带认证的 Nginx 反向代理使用。

---

## 💻 开发方式

本项目由纯 **AI 结对编程** (AI Pair Programming) 驱动开发构建。
- **技术栈**：后端采用 `FastAPI` (高并发异步调度)，前端采用 `Vue 3` + `TailwindCSS` 打造极简的极客风控制台。
- **AI 协作**：从核心架构设计、分布式通信实现，到美观的 UI 组件与重试容错机制，均系与先进的大语言模型共同思考迭代完成，代码具有极高的现代化标准与注释覆盖率。

---

## 🙏 致谢

SSUBB 的诞生离不开开源社区的伟大贡献，特别感谢以下项目和技术（包含直接引用或灵感参考）：
- [OpenAI Whisper](https://github.com/openai/whisper) / [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper)：提供卓越的语音转写基础。
- [MoviePilot](https://github.com/jxxghp/MoviePilot)：极其优秀的自动化媒体库管理系统。
- [subgen](https://github.com/McCloudS/subgen)：启发了本项目网络分布式提取与字幕工作流的灵感。
- [VideoCaptioner](https://github.com/WEIFENG2333/VideoCaptioner)：启发了长视频大语言模型分片翻译防截断优化思路。
- DeepSeek / 智谱 等 API 厂商：让高质量 AI 翻译变得廉价可及。

---

## 📄 分发与版权 (License)

本项目基于 **MIT License** 协议开源。
您可以自由地使用、修改、分发甚至用于商业用途，只需保留原作者的版权声明即可。

> **免责声明**：本项目仅供学习与技术交流使用，请勿用于任何违反法律法规的用途。由于 AI 翻译存在不可控性，开发者不对生成字幕的准确性、适用性负责。

---

## 🙋 遇到问题？

1. 优先查看 NAS 控制台（`http://NAS的IP:8787`）的实时日志看板。
2. 检查 Worker 终端的输出。
3. 大部分问题是网络不通或配置（尤其是 IP 地址和端口）填错，请善用 `scripts/check_env.ps1` 进行自检。
