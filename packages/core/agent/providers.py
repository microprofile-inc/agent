"""供应商管理：从 config.toml 加载，统一走 OpenAI 兼容协议。"""

import os
import tomllib
from pathlib import Path

from openai import OpenAI

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config.toml"


def _load_config() -> dict:
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def _resolve_key(spec: dict) -> str:
    """按配置取 API key：key_file 文件最后一行，或 key_env 环境变量。"""
    if "key_file" in spec:
        path = os.path.expanduser(spec["key_file"])
        return open(path).read().strip().splitlines()[-1].strip()
    return os.environ[spec["key_env"]]


class ProviderRegistry:
    """供应商注册表：按名称创建 OpenAI client，查询可用模型。"""

    def __init__(self, config_path: Path = CONFIG_PATH):
        with open(config_path, "rb") as f:
            self._providers = tomllib.load(f)["providers"]

    def names(self) -> list[str]:
        return list(self._providers)

    def default_model(self, name: str) -> str:
        return self._providers[name]["default_model"]

    def models(self, name: str) -> list[str]:
        spec = self._providers[name]
        return spec.get("models", [spec["default_model"]])

    def client(self, name: str) -> OpenAI:
        spec = self._providers[name]
        return OpenAI(
            api_key=_resolve_key(spec),
            base_url=spec.get("base_url") or None,
        )
