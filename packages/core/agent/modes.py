"""模式系统：THINK 只思考不执行，ACT 思考并执行工具。"""

from enum import Enum


class Mode(Enum):
    THINK = "think"  # 收到 tool_calls 时不执行，仅展示模型意图
    ACT = "act"  # 正常执行工具

    @classmethod
    def parse(cls, s: str) -> "Mode":
        return cls(s.strip().lower())
