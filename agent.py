import json
import subprocess
import urllib.request

# 从 ~/.deepseek_key 读取 API key（取文件最后一行，兼容带说明文字的格式）
KEY = (
    open(f"{__import__('os').path.expanduser('~')}/.deepseek_key")
    .read()
    .strip()
    .splitlines()[-1]
    .strip()
)

# DeepSeek 对话补全接口地址
URL = "https://api.deepseek.com/chat/completions"
# 工具定义：声明给模型的可用工具（function calling 格式）
TOOLS = [
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
    }
]


def run_shell(command):
    """执行 shell 命令，返回标准输出+标准错误；60 秒超时"""
    r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
    return (r.stdout + r.stderr).strip() or "(no output)"


def chat(messages):
    """调用 DeepSeek 接口，发送完整对话历史，返回模型的回复消息"""
    req = urllib.request.Request(
        URL,
        json.dumps(
            {
                "model": "deepseek-v4-pro",
                "messages": messages,
                "tools": TOOLS,
            }
        ).encode(),
        {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req))["choices"][0]["message"]


# 对话历史，首条为系统提示词
messages = [
    {
        "role": "system",
        "content": "You are a terminal agent. Use run_shell to complete tasks.",
    }
]
# 外层循环：交互式读取用户输入
while True:
    try:
        user = input("> ")
    except (EOFError, KeyboardInterrupt):  # Ctrl-D / Ctrl-C 退出
        break
    if user in ("exit", "quit"):
        break
    messages.append({"role": "user", "content": user})
    # 内层循环：agent loop —— 模型可能多次调用工具，直到返回纯文本回复
    while True:
        msg = chat(messages)  # 请求模型
        messages.append(msg)  # 把模型回复记入历史
        if not msg.get("tool_calls"):  # 没有工具调用 = 最终答案，打印并结束本轮
            print(msg["content"])
            break
        for tc in msg["tool_calls"]:  # 逐个执行模型请求的工具调用
            args = json.loads(tc["function"]["arguments"])
            print(f"$ {args['command']}")  # 回显将要执行的命令
            messages.append(
                {  # 工具执行结果回传给模型，继续循环
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": run_shell(args["command"]),
                }
            )
