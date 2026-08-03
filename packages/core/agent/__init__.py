"""Agent 核心引擎：纯逻辑，零 IO 依赖，供 terminal / server / desktop 复用。"""

from .loop import Agent, Event
from .modes import Mode

__all__ = ["Agent", "Event", "Mode"]
