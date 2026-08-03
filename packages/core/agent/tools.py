"""工具注册表：工具定义 + 执行分发。"""

import subprocess

# 发给模型的 function calling 工具定义
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a shell command and return its output",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "Recall long-term memories older than the default 7-day window. Use when the user asks about things discussed long ago. Read-only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "what to recall"},
                    "days": {"type": "integer", "description": "look back this many days, default 30"},
                },
                "required": ["query"],
            },
        },
    },
]


def run_shell(command: str) -> str:
    """执行 shell 命令，返回标准输出+标准错误；60 秒超时。"""
    r = subprocess.run(
        command, shell=True, capture_output=True, text=True, timeout=60
    )
    return (r.stdout + r.stderr).strip() or "(no output)"


# 工具名 → 执行函数
DISPATCH = {"run_shell": run_shell}


def execute(name: str, args: dict) -> str:
    fn = DISPATCH.get(name)
    if fn is None:
        return f"(unknown tool: {name})"
    return fn(**args)
