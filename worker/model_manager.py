"""SSUBB Worker - 模型管理

Whisper 模型的下载、检测、清理和版本管理。
"""

import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ssubb.model_manager")

# =============================================================================
# 已知模型注册表
# =============================================================================

KNOWN_MODELS = {
    "tiny": {
        "repo": "Systran/faster-whisper-tiny",
        "size_mb": 75,
        "description": "最小模型，速度最快，精度最低",
    },
    "base": {
        "repo": "Systran/faster-whisper-base",
        "size_mb": 145,
        "description": "基础模型，适合简单场景",
    },
    "small": {
        "repo": "Systran/faster-whisper-small",
        "size_mb": 488,
        "description": "小型模型，速度/精度平衡",
    },
    "medium": {
        "repo": "Systran/faster-whisper-medium",
        "size_mb": 1530,
        "description": "中型模型，推荐最低 4GB VRAM",
    },
    "large-v3": {
        "repo": "Systran/faster-whisper-large-v3",
        "size_mb": 3070,
        "description": "大型模型 v3，推荐 8GB+ VRAM",
    },
    "large-v3-turbo": {
        "repo": "Systran/faster-whisper-large-v3-turbo",
        "size_mb": 1620,
        "description": "大型模型 v3-turbo，速度快精度高，推荐首选",
    },
}


class ModelManager:
    """Whisper 模型管理器"""

    def __init__(self, model_dir: str = "./models"):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

    def list_models(self) -> list[dict]:
        """列出所有已知模型及其本地状态"""
        results = []
        for name, info in KNOWN_MODELS.items():
            local = self._find_local_model(name)
            results.append({
                "name": name,
                "repo": info["repo"],
                "size_mb": info["size_mb"],
                "description": info["description"],
                "installed": local is not None,
                "local_path": str(local) if local else None,
                "local_size_mb": self._get_dir_size_mb(local) if local else 0,
            })
        return results

    def is_installed(self, model_name: str) -> bool:
        """检查模型是否已下载"""
        return self._find_local_model(model_name) is not None

    def get_model_path(self, model_name: str) -> Optional[str]:
        """获取模型本地路径"""
        path = self._find_local_model(model_name)
        return str(path) if path else None

    def download_model(self, model_name: str) -> bool:
        """下载模型 (通过 huggingface_hub 或 faster-whisper 自动下载)

        Returns:
            是否成功
        """
        if model_name not in KNOWN_MODELS:
            logger.error(f"未知模型: {model_name}")
            logger.info(f"已知模型: {', '.join(KNOWN_MODELS.keys())}")
            return False

        info = KNOWN_MODELS[model_name]
        logger.info(f"准备下载模型: {model_name} (~{info['size_mb']}MB)")
        logger.info(f"  来源: {info['repo']}")
        logger.info(f"  目标: {self.model_dir}")

        try:
            # 方法 1: 使用 huggingface_hub (推荐)
            try:
                from huggingface_hub import snapshot_download
                local_path = snapshot_download(
                    info["repo"],
                    local_dir=str(self.model_dir / f"faster-whisper-{model_name}"),
                    local_dir_use_symlinks=False,
                )
                logger.info(f"模型下载完成: {local_path}")
                return True
            except ImportError:
                pass

            # 方法 2: 使用 faster-whisper 内置下载
            try:
                from faster_whisper.utils import download_model
                local_path = download_model(
                    model_name,
                    output_dir=str(self.model_dir),
                )
                logger.info(f"模型下载完成: {local_path}")
                return True
            except ImportError:
                pass

            # 方法 3: ctranslate2 自动下载 (会在首次转写时触发)
            logger.warning(
                f"无法主动下载模型 (缺少 huggingface_hub 或 faster-whisper)。"
                f"模型将在首次转写时自动下载到 {self.model_dir}"
            )
            return False

        except Exception as e:
            logger.exception(f"模型下载失败: {e}")
            return False

    def delete_model(self, model_name: str) -> bool:
        """删除本地模型"""
        path = self._find_local_model(model_name)
        if path is None:
            logger.warning(f"模型未安装: {model_name}")
            return False

        try:
            shutil.rmtree(path)
            logger.info(f"已删除模型: {model_name} ({path})")
            return True
        except Exception as e:
            logger.error(f"删除模型失败: {e}")
            return False

    def get_status(self) -> dict:
        """获取模型管理状态摘要"""
        models = self.list_models()
        installed = [m for m in models if m["installed"]]
        total_size = sum(m["local_size_mb"] for m in installed)
        return {
            "model_dir": str(self.model_dir),
            "total_known": len(KNOWN_MODELS),
            "installed_count": len(installed),
            "installed_models": [m["name"] for m in installed],
            "total_size_mb": round(total_size, 1),
            "disk_free_gb": round(shutil.disk_usage(self.model_dir).free / (1024**3), 1),
        }

    # =========================================================================
    # 内部方法
    # =========================================================================

    def _find_local_model(self, model_name: str) -> Optional[Path]:
        """查找本地模型目录"""
        candidates = [
            self.model_dir / model_name,
            self.model_dir / f"faster-whisper-{model_name}",
            self.model_dir / f"models--Systran--faster-whisper-{model_name}",
        ]
        for path in candidates:
            if path.exists() and path.is_dir():
                # 检查是否有实际模型文件
                bin_files = list(path.rglob("*.bin"))
                if bin_files:
                    return path
        return None

    @staticmethod
    def _get_dir_size_mb(path: Optional[Path]) -> float:
        """计算目录大小 (MB)"""
        if path is None or not path.exists():
            return 0
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return total / (1024 * 1024)


if __name__ == "__main__":
    import json
    mgr = ModelManager()
    print("\n模型管理状态:")
    print(json.dumps(mgr.get_status(), indent=2, ensure_ascii=False))
    print("\n可用模型:")
    for m in mgr.list_models():
        status = "✅ 已安装" if m["installed"] else "⬜ 未安装"
        print(f"  {status}  {m['name']:20s}  ~{m['size_mb']:>5d}MB  {m['description']}")
