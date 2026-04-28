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
| `coordinator.worker.url` | NAS 端 config.yaml | GPU 机器地址，如 `http://192.168.1.50:8788` |
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

## 📁 项目结构（给好奇的人看）

```
SSUBB/
├── coordinator/          # NAS 端 — 任务调度 + WebUI + 字幕写入
├── worker/               # GPU 端 — 语音转写 + AI 翻译
├── shared/               # 两端共用的代码
├── moviepilot-plugin/    # MoviePilot 插件
├── config.example.yaml   # 配置模板（复制为 config.yaml 再改）
├── docker-compose.yml    # Docker 部署（高级用户）
└── docs/                 # 详细文档
    ├── architecture.md   # 架构设计
    ├── configuration.md  # 配置详解
    └── roadmap.md        # 开发路线
```

---

## 🐳 Docker 部署（NAS 用户推荐）

如果你的 NAS 支持 Docker（群晖、威联通等）：

```bash
# 先编辑 config.yaml 和 docker-compose.yml 里的路径映射
docker compose up -d
```

> ⚠️ `docker-compose.yml` 里的 volumes 需要把你的影视目录挂载进去，路径要和实际一致。

---

## 🙋 遇到问题？

1. 先看控制台（`http://NAS的IP:8787`）的日志面板
2. 看 Worker 终端的输出
3. 大部分问题是网络不通或配置填错
