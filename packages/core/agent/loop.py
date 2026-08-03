"""Agent 主循环：流式输出 → 事件流 → 模式调度 + 记忆 + 上下文压缩。"""

import json
import re
from dataclasses import dataclass
from typing import Callable, Iterator

from .memory import EbbinghausMemory, NullMemory
from .modes import Mode
from .tools import TOOL_SCHEMAS, execute

SYSTEM_PROMPT = "You are a terminal agent. Use run_shell to complete tasks."
THINK_NOTICE = "（当前为思考模式，不执行任何操作，仅展示计划）"
EXTRACT_PROMPT = """从以下对话中抽取值得长期记住的事实或用户偏好，输出 JSON 数组，每条 {{"content": "...", "kind": "soft|hard"}}。
kind=hard：路径、URL、凭据、端口、明确决策等不可遗忘的事实。
kind=soft：偏好、习惯、临时上下文等可随时间遗忘的信息。
没有值得记住的内容就输出 []。只输出 JSON，不要其他文字。

用户：{user}
助手：{assistant}"""
COMPRESS_PROMPT = "把以下对话历史压缩成一段简洁的摘要，保留关键事实、决策和上下文，只输出摘要文本：\n\n{history}"

# 危险命令模式：执行前需确认（confirm 为 None 时直接拦截）
DANGEROUS = re.compile(
    r"\brm\b|\bmv\b|\bdd\b|mkfs|format|\bsudo\b|>\s*/|drop\s+table|truncate|delete\s+from",
    re.IGNORECASE,
)
# 上下文压缩阈值：历史消息总字符数
COMPRESS_CHARS = 20000
# 压缩时保留最近的消息条数
COMPRESS_KEEP = 6


@dataclass
class Event:
    """前端消费的事件：kind ∈ text_delta / tool_call / tool_result / done。"""

    kind: str
    data: dict


class Agent:
    def __init__(self, client, model: str, mode: Mode = Mode.ACT,
                 memory=None, messages: list | None = None,
                 session_id: str = "", on_message=None,
                 confirm: Callable[[str], bool] | None = None):
        self.client = client
        self.model = model
        self.mode = mode
        self.memory = memory or NullMemory()
        self.messages = messages if messages is not None else [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        self.session_id = session_id
        # 消息持久化回调（session 落盘），可选
        self.on_message = on_message
        # 危险命令确认回调：返回 True 才执行；None = 拦截所有危险命令
        self.confirm = confirm

    def _record(self, msg: dict) -> None:
        self.messages.append(msg)
        if self.on_message:
            self.on_message(msg)

    # ---------- 上下文压缩 ----------

    def _compress_context(self) -> None:
        """历史超长时，把早期消息压缩成摘要，保留 system + 最近若干条。"""
        total = sum(len(json.dumps(m, ensure_ascii=False)) for m in self.messages)
        if total < COMPRESS_CHARS or len(self.messages) <= COMPRESS_KEEP + 1:
            return
        old = self.messages[1:-COMPRESS_KEEP]
        history = "\n".join(
            f"{m.get('role')}: {m.get('content', '')}" for m in old
        )
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": COMPRESS_PROMPT.format(history=history)}],
            )
            summary = resp.choices[0].message.content or ""
        except Exception:
            return
        # 摘要作为 system 消息插在原 system 之后
        self.messages = (
            self.messages[:1]
            + [{"role": "system", "content": f"此前对话摘要：{summary}"}]
            + self.messages[-COMPRESS_KEEP:]
        )

    # ---------- 流式请求 ----------

    def _chat_stream(self, messages: list, tools=None):
        """流式请求，yield ('delta', text) 增量，最后 yield ('final', content, tool_calls)。"""
        resp = self.client.chat.completions.create(
            model=self.model, messages=messages, tools=tools, stream=True
        )
        content = ""
        tool_calls: dict[int, dict] = {}
        for chunk in resp:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if not delta:
                continue
            if delta.content:
                content += delta.content
                yield ("delta", delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    slot = tool_calls.setdefault(
                        tc.index, {"id": "", "type": "function",
                                   "function": {"name": "", "arguments": ""}})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            slot["function"]["name"] += tc.function.name
                        if tc.function.arguments:
                            slot["function"]["arguments"] += tc.function.arguments
        yield ("final", content, [tool_calls[i] for i in sorted(tool_calls)])

    def _chat(self, messages: list, tools=None):
        resp = self.client.chat.completions.create(
            model=self.model, messages=messages, tools=tools
        )
        return resp.choices[0].message

    # ---------- 记忆 ----------

    def _extract_memories(self, user_input: str, answer: str) -> None:
        """每轮结束：调 LLM 抽取记忆并落库，失败静默忽略。"""
        try:
            msg = self._chat(
                [{"role": "user", "content": EXTRACT_PROMPT.format(
                    user=user_input, assistant=answer)}],
                tools=None,
            )
            text = (msg.content or "").strip()
            items = json.loads(text[text.index("["):text.rindex("]") + 1])
            if isinstance(items, list):
                self.memory.write(items, self.session_id)
        except Exception:
            pass

    def _recall(self, args: dict) -> str:
        """recall_memory 工具：扩大窗口回溯，只读（强化也算复习）。"""
        hits = self.memory.recall(
            args["query"], days=int(args.get("days", 30)))
        return "\n".join(f"- {h}" for h in hits) or "(没有更早的相关记忆)"

    # ---------- 工具执行 ----------

    def _execute_tool(self, name: str, args: dict) -> str:
        """危险命令确认：confirm 为 None 拦截，confirm 返回 False 拒绝。"""
        if name == "run_shell":
            cmd = args.get("command", "")
            if DANGEROUS.search(cmd):
                if self.confirm is None:
                    return "(危险命令已被安全策略拦截，未执行)"
                if not self.confirm(cmd):
                    return "(用户拒绝执行该命令)"
        return execute(name, args)

    # ---------- 主循环 ----------

    def run_turn(self, user_input: str) -> Iterator[Event]:
        """处理一轮用户输入，流式产生事件直到模型给出最终文本。"""
        self._compress_context()
        recalled = self.memory.read(user_input)
        content = f"{recalled}\n\n{user_input}" if recalled else user_input
        self._record({"role": "user", "content": content})

        answer = ""
        while True:
            # 流式请求：delta 实时透出，final 汇总
            text, tool_calls = "", []
            for kind, *payload in self._chat_stream(self.messages, tools=TOOL_SCHEMAS):
                if kind == "delta":
                    text += payload[0]
                    yield Event("text_delta", {"delta": payload[0]})
                else:
                    text, tool_calls = payload

            msg = {"role": "assistant", "content": text or None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            self._record({k: v for k, v in msg.items() if v is not None})

            # 无工具调用 = 最终答案
            if not tool_calls:
                answer = text
                self._extract_memories(user_input, answer)
                yield Event("done", {})
                return

            # 思考模式：recall_memory（只读）放行，其余拦截只展示意图
            if self.mode is Mode.THINK:
                side_effect = [tc for tc in tool_calls if tc["function"]["name"] != "recall_memory"]
                for tc in tool_calls:
                    if tc["function"]["name"] == "recall_memory":
                        self._record({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": self._recall(json.loads(tc["function"]["arguments"])),
                        })
                if not side_effect:
                    continue  # 只有 recall，让模型基于记忆继续回答
                plan = [
                    {"tool": tc["function"]["name"], "args": json.loads(tc["function"]["arguments"])}
                    for tc in side_effect
                ]
                yield Event("text_delta", {"delta": f"\n\n{THINK_NOTICE}\n```json\n{json.dumps(plan, ensure_ascii=False, indent=2)}\n```"})
                yield Event("done", {})
                return

            # 执行模式：逐个执行工具并回传结果
            for tc in tool_calls:
                name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"])
                yield Event("tool_call", {"tool": name, "args": args})
                result = self._recall(args) if name == "recall_memory" else self._execute_tool(name, args)
                yield Event("tool_result", {"tool": name, "result": result})
                self._record({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })
