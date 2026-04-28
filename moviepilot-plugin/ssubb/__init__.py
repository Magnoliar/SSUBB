from typing import Any, Dict, List, Tuple
from pathlib import Path

# Note: The following imports are available in the MoviePilot V2 environment
try:
    from app.core.event import eventmanager, Event
    from app.plugins import _PluginBase
    from app.schemas.types import EventType, MediaType
    from app.log import logger
    from app.utils.http import RequestUtils
    HAS_MOVIEPILOT = True
except ImportError:
    HAS_MOVIEPILOT = False
    class _PluginBase: pass
    class Event: pass
    class EventType: TransferComplete = "transfer_complete"
    class eventmanager:
        @staticmethod
        def register(*args, **kwargs):
            return lambda f: f
    
    import logging
    logger = logging.getLogger("ssubb_plugin")
    class RequestUtils:
        def __init__(self, *args, **kwargs): pass
        def post(self, url, json=None, **kwargs): pass
        def get(self, url, params=None, **kwargs): pass


class SSUBBPlugin(_PluginBase):
    # 插件名称
    plugin_name = "SSUBB 字幕转写"
    # 插件描述
    plugin_desc = "异地分布式 AI 字幕转写翻译 — 自动为入库外语影视生成中文字幕"
    # 插件图标
    plugin_icon = "subtitle.png"
    # 插件版本
    plugin_version = "0.4.0"
    # 插件作者
    plugin_author = "SSUBB"
    # 作者主页
    author_url = "https://github.com/SSUBB"
    # 插件配置项ID前缀
    plugin_config_prefix = "ssubb_"
    # 加载顺序
    plugin_order = 30
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _coordinator_url = ""
    _auto_on_transfer = True
    _target_lang = "zh"
    _source_lang = "auto"
    _force_mode = False
    _local_path = ""
    _remote_path = ""

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled", False)
            self._coordinator_url = config.get("coordinator_url", "").rstrip("/")
            if self._coordinator_url and not self._coordinator_url.startswith("http"):
                self._coordinator_url = "http://" + self._coordinator_url
            
            self._auto_on_transfer = config.get("auto_on_transfer", True)
            self._target_lang = config.get("target_lang", "zh")
            self._source_lang = config.get("source_lang", "auto")
            self._force_mode = config.get("force_mode", False)
            self._local_path = config.get("local_path", "")
            self._remote_path = config.get("remote_path", "")

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """注册插件暴露的 API"""
        return [
            {
                "path": "/callback",
                "endpoint": self._on_coordinator_callback,
                "methods": ["POST"],
                "summary": "接收 SSUBB 状态回调"
            }
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面
        返回: (表单组件列表, 默认配置字典)
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    # ---- 开关行 ----
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'enabled',
                                        'label': '启用插件',
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'auto_on_transfer',
                                        'label': '入库自动触发',
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'force_mode',
                                        'label': '强制模式 (覆盖已有字幕)',
                                    }
                                }]
                            },
                        ]
                    },
                    # ---- 连接配置 ----
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'coordinator_url',
                                        'label': 'SSUBB Coordinator 地址',
                                        'placeholder': 'http://192.168.1.10:8787',
                                        'hint': 'NAS 上运行的 Coordinator 地址',
                                        'persistent-hint': True,
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 3},
                                'content': [{
                                    'component': 'VSelect',
                                    'props': {
                                        'model': 'target_lang',
                                        'label': '目标语言',
                                        'items': [
                                            {'title': '中文', 'value': 'zh'},
                                            {'title': 'English', 'value': 'en'},
                                            {'title': '日本語', 'value': 'ja'},
                                            {'title': '한국어', 'value': 'ko'},
                                            {'title': 'Français', 'value': 'fr'},
                                            {'title': 'Deutsch', 'value': 'de'},
                                        ],
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 3},
                                'content': [{
                                    'component': 'VSelect',
                                    'props': {
                                        'model': 'source_lang',
                                        'label': '源语言',
                                        'items': [
                                            {'title': '自动检测', 'value': 'auto'},
                                            {'title': 'English', 'value': 'en'},
                                            {'title': '日本語', 'value': 'ja'},
                                            {'title': 'Français', 'value': 'fr'},
                                            {'title': 'Deutsch', 'value': 'de'},
                                            {'title': '한국어', 'value': 'ko'},
                                        ],
                                    }
                                }]
                            },
                        ]
                    },
                    # ---- 路径映射 ----
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'local_path',
                                        'label': 'MoviePilot 本地路径前缀',
                                        'placeholder': '/media',
                                        'hint': 'MoviePilot 容器内的媒体路径前缀',
                                        'persistent-hint': True,
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'remote_path',
                                        'label': 'Coordinator 侧路径前缀',
                                        'placeholder': '/volume1/media',
                                        'hint': 'SSUBB Coordinator 看到的同一目录的路径',
                                        'persistent-hint': True,
                                    }
                                }]
                            },
                        ]
                    },
                    # ---- 使用说明 ----
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [{
                                    'component': 'VAlert',
                                    'props': {
                                        'type': 'info',
                                        'variant': 'tonal',
                                        'text': 'SSUBB 是独立运行的异地分布式字幕系统。'
                                                '启用后，MoviePilot 入库的外语影视将自动提交到 SSUBB Coordinator 生成中文字幕。'
                                                '完成后会通过 MoviePilot 通知系统发送消息。'
                                                '如果 MoviePilot 和 SSUBB 的媒体目录挂载路径不同，'
                                                '请配置"路径映射"将 MoviePilot 路径转换为 Coordinator 路径。'
                                                '详细管理请访问 SSUBB 独立控制台。'
                                    }
                                }]
                            }
                        ]
                    },
                ]
            }
        ], {
            "enabled": False,
            "coordinator_url": "",
            "auto_on_transfer": True,
            "target_lang": "zh",
            "source_lang": "auto",
            "force_mode": False,
            "local_path": "",
            "remote_path": "",
        }

    def _on_coordinator_callback(self, payload: dict) -> dict:
        """收到 Coordinator 的完成回调，发送消息"""
        from app.schemas import NotificationType
        task_id = payload.get("task_id", "")
        media_title = payload.get("media_title", "未知媒体")
        status = payload.get("status", "")
        message = payload.get("message", "")
        time_cost = payload.get("time_cost", 0)
        
        logger.info(f"收到 SSUBB 任务回调 [{task_id}] {media_title}: {status}")
            
        mtype = NotificationType.Software
        
        # 使用 MoviePilot 原生通知系统发送消息
        try:
            if status == "completed":
                self.post_message(
                    mtype=mtype,
                    title="🎬 SSUBB 智能字幕生成完毕",
                    text=f"**影片**: {media_title}\n**状态**: 成功写回中文字幕\n**统计**: 核心环节耗时约 {time_cost} 秒"
                )
            else:
                self.post_message(
                    mtype=mtype,
                    title="⚠️ SSUBB 智能字幕生成失败",
                    text=f"**影片**: {media_title}\n**错误**: {message}\n请进入独立 Web 控制台查看详细日志。"
                )
        except Exception as e:
            logger.error(f"发送 SSUBB 通知失败: {e}")

        return {"success": True}

    def get_page(self) -> List[dict]:
        """插件详情页: 构建精简面板 + 导向独立 Web 界面"""
        # 实时请求当前 Coordinator 状态
        stats = {"total": 0, "completed": 0, "pending": 0}
        try:
            res = RequestUtils(timeout=3).get(f"{self._coordinator_url}/api/status")
            if res and res.status_code == 200:
                stats_res = res.json()
                stats = {
                    "pending": stats_res.get("tasks_pending", 0),
                    "active": stats_res.get("tasks_active", 0), 
                    "completed": stats_res.get("tasks_completed", 0)
                }
        except:
            pass

        return [
            {
                "component": "div",
                "content": [
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "title": "SSUBB 独立数据大屏",
                            "text": f"SSUBB 是独立的高可用跨端微服务架构。为提供最极客的管理体验，请直接访问 Coordinator 面板以管理队列和干预生成。",
                            "class": "mb-4"
                        }
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VCard",
                                    "props": {"title": "处理中任务", "subtitle": str(stats["active"]), "color": "primary", "variant": "tonal"}
                                }]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VCard",
                                    "props": {"title": "排队等待中", "subtitle": str(stats["pending"]), "color": "warning", "variant": "tonal"}
                                }]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VCard",
                                    "props": {"title": "已成功处理", "subtitle": str(stats["completed"]), "color": "success", "variant": "tonal"}
                                }]
                            }
                        ]
                    },
                    {
                        "component": "div",
                        "props": {"class": "mt-5 d-flex justify-center"},
                        "content": [
                            {
                                "component": "VBtn",
                                "props": {
                                    "color": "primary",
                                    "size": "large",
                                    "prependIcon": "mdi-open-in-new",
                                    "href": self._coordinator_url or "#",
                                    "target": "_blank",
                                    "text": "打开 SSUBB 独立控制台"
                                }
                            }
                        ]
                    }
                ]
            }
        ]

    def stop_service(self):
        """停止插件"""
        pass

    @eventmanager.register(EventType.TransferComplete)
    def on_transfer_complete(self, event: Event):
        """媒体入库完成事件 → 自动创建字幕任务"""
        if not self._enabled or not self._auto_on_transfer or not self._coordinator_url:
            return

        item = event.event_data
        if not item:
            return

        # 获取影片信息
        item_media = item.get("mediainfo")
        item_transfer = item.get("transferinfo")
        
        if not item_media or not item_transfer:
            return
            
        media_type = "movie" if item_media.type == MediaType.MOVIE else "tv"
        media_title = item_media.title
        tmdb_id = item_media.tmdb_id
        season = item_media.season
        episode = item_media.episode
        
        # 文件列表
        file_list = getattr(item_transfer, "file_list_new", [])
        if not file_list:
            if hasattr(item_transfer, "target_diritem") and hasattr(item_transfer.target_diritem, "path"):
                file_list = [Path(item_transfer.target_diritem.path) / item_transfer.target_diritem.name]

        for file_path in file_list:
            file_path_str = str(file_path)
            
            # 路径转换
            if self._local_path and self._remote_path and file_path_str.startswith(self._local_path):
                file_path_str = file_path_str.replace(self._local_path, self._remote_path).replace('\\', '/')

            logger.info(f"媒体入库: {media_title} → 通知 SSUBB 创建字幕任务: {file_path_str}")

            self._create_task(
                media_path=file_path_str,
                media_title=media_title,
                media_type=media_type,
                tmdb_id=tmdb_id,
                season=season,
                episode=episode,
                force=self._force_mode
            )

    def _create_task(self, media_path: str, media_title: str = "",
                     media_type: str = "unknown", tmdb_id: int = None,
                     season: int = None, episode: int = None,
                     force: bool = False):
        """通过 HTTP 调用 Coordinator 创建任务，并带入回调地址"""
        req_url = f"{self._coordinator_url}/api/task"
        
        # 获取当前插件体系自身的基准请求地址给远端
        # MoviePilot V2 中, 插件 API 形如: /api/v1/plugins/{plugin_id}/{path}
        # 但我们不知道外部地址，需要依赖系统。简单做法：从配置文件反查或直接用环境变量
        from app.core.config import settings
        site_host = "http://127.0.0.1:3000"  # Fallback
        if hasattr(settings, "WEB_HOST") and settings.WEB_HOST:
            site_host = settings.WEB_HOST
            
        callback_url = f"{site_host.rstrip('/')}/api/v1/plugins/{self.__class__.__name__}/callback"
        
        payload = {
            "media_path": media_path,
            "media_title": media_title,
            "media_type": media_type,
            "source_lang": self._source_lang,
            "target_lang": self._target_lang,
            "force": force,
            "callback_url": callback_url
        }
        if tmdb_id:
            payload["tmdb_id"] = tmdb_id
        if season is not None:
            payload["season"] = season
        if episode is not None:
            payload["episode"] = episode

        try:
            res = RequestUtils().post(req_url, json=payload)
            if res and res.status_code == 200:
                result = res.json()
                task_id = result.get("id", "unknown")
                status = result.get("status", "unknown")
                logger.info(f"SSUBB 任务已创建: {task_id} (status={status})")
            else:
                code = res.status_code if res else "Unknown"
                logger.error(f"创建 SSUBB 任务失败: HTTP {code}")
        except Exception as e:
            logger.error(f"连接 SSUBB Coordinator 失败: {e}")
