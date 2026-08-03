"""Textual TUI 前端：侧边栏会话 + Markdown 对话流 + 流式输出。

分层说明：parse_command / fmt_time / Command 与 Textual 无关，
将来迁移其他前端（如 opentui）时这部分可直接带走。
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "core"))

from agent.loop import Agent
from agent.memory import EbbinghausMemory
from agent.modes import Mode
from agent.providers import ProviderRegistry
from agent.session import Session, SessionStore
from agent.tools import run_shell

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    Markdown,
    Static,
)

# ================= 框架无关层（可迁移） =================

HELP_TEXT = """/mode think|act  切换模式    /provider <名>  切换供应商
/model <名>      切换模型    /new [标题]     新建会话
/search <词>     搜索会话    /help           帮助
!<命令>          直接执行 shell（不经过 LLM）"""


@dataclass
class Command:
    name: str
    arg: str


def parse_command(text: str) -> Command | None:
    """解析 / 斜杠命令，非命令返回 None。"""
    if not text.startswith("/"):
        return None
    parts = text.split(maxsplit=1)
    return Command(parts[0][1:], parts[1] if len(parts) > 1 else "")


def fmt_time(ts: float) -> str:
    return time.strftime("%m-%d %H:%M", time.localtime(ts))


# ================= Textual 组件层 =================

class ConfirmScreen(ModalScreen[bool]):
    """危险命令确认弹窗：y 执行 / n 拒绝。"""

    BINDINGS = [
        Binding("y", "confirm(True)", "执行"),
        Binding("n", "confirm(False)", "拒绝"),
        Binding("escape", "confirm(False)", "拒绝"),
    ]

    def __init__(self, command: str):
        super().__init__()
        self.command = command

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(f"⚠️ 危险命令，确认执行？\n\n{self.command}")
            with Horizontal(id="confirm-buttons"):
                yield Button("执行 (y)", variant="error", id="yes")
                yield Button("拒绝 (n)", id="no")

    def action_confirm(self, result: bool) -> None:
        self.dismiss(result)

    @on(Button.Pressed, "#yes")
    def on_yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def on_no(self) -> None:
        self.dismiss(False)


class ToolCard(Static):
    """工具调用卡片：$ 命令 + 输出结果。"""

    def __init__(self, tool: str, args: dict):
        super().__init__("", classes="tool-card")
        self.tool = tool
        self.args = args
        cmd = args.get("command", str(args))
        self.update(f"$ {cmd}\n⏳ 执行中…")

    def set_result(self, result: str) -> None:
        cmd = self.args.get("command", str(self.args))
        shown = result if len(result) < 2000 else result[:2000] + "\n…(截断)"
        self.update(f"$ {cmd}\n{shown}")


class ChatApp(App):
    CSS = """
    #sidebar { width: 28; border-right: solid $primary; }
    #sidebar Input { margin: 0 1; }
    #chat { height: 1fr; padding: 0 2; }
    #input-bar { height: auto; dock: bottom; }
    #status { height: 1; background: $panel; padding: 0 1; }
    .msg-user { margin: 1 0 0 4; color: $text; }
    .msg-assistant { margin: 0 0 0 1; }
    .tool-card {
        margin: 0 0 0 1; padding: 0 1;
        background: $surface; border: round $primary-darken-2;
    }
    #confirm-dialog {
        width: 60; height: auto; padding: 1 2;
        background: $surface; border: thick $error;
    }
    #confirm-buttons { height: auto; align-horizontal: right; }
    """

    BINDINGS = [
        Binding("ctrl+t", "toggle_mode", "切换模式"),
        Binding("ctrl+n", "new_session", "新建会话"),
        Binding("ctrl+q", "quit", "退出"),
    ]

    def __init__(self):
        super().__init__()
        self.store = SessionStore()
        self.registry = ProviderRegistry()
        self.memory = EbbinghausMemory()
        self.provider = self.registry.names()[0]
        self.session: Session | None = None
        self.agent: Agent | None = None
        # 流式状态：当前 assistant 的 Markdown 组件与累积文本
        self._cur_md: Markdown | None = None
        self._cur_text = ""
        self._cur_tool: ToolCard | None = None

    # ---------- 布局 ----------

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Input(placeholder="搜索会话…", id="search")
                yield ListView(id="session-list")
                yield Button("+ 新建会话", id="new-btn")
            with Vertical():
                yield Static("", id="status")
                yield VerticalScroll(id="chat")
                yield Input(placeholder="输入消息，/命令 !shell，Enter 发送", id="input-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_sessions(select_latest=True)
        self.query_one("#input-bar", Input).focus()

    # ---------- 状态栏 / 会话 ----------

    def _status(self) -> None:
        if self.agent:
            title = self.session.title if self.session else "-"
            self.query_one("#status", Static).update(
                f" {title} | {self.provider} · {self.agent.model} · [{self.agent.mode.value.upper()}]"
                "  (^T 模式 ^N 新会话 ^Q 退出)"
            )

    def _make_agent(self) -> None:
        self.agent = Agent(
            client=self.registry.client(self.provider),
            model=self.registry.default_model(self.provider),
            messages=self.session.messages or None,
            session_id=self.session.id,
            memory=self.memory,
            on_message=lambda m: self.store.append(self.session.id, m),
            confirm=self._confirm_dangerous,
        )
        self._status()

    def refresh_sessions(self, keyword: str = "", select_latest: bool = False) -> None:
        lv = self.query_one("#session-list", ListView)
        lv.clear()
        if keyword:
            sessions = [s for s, _ in self.store.search(keyword)]
        else:
            sessions = self.store.list()
        for s in sessions:
            lv.append(ListItem(Label(f"{s.title}  ({fmt_time(s.updated_at)})"), name=s.id))
        if select_latest:
            if sessions:
                self.load_session(sessions[0].id)
            else:
                self.new_session()

    def load_session(self, session_id: str) -> None:
        self.session = self.store.load(session_id)
        self._make_agent()
        chat = self.query_one("#chat", VerticalScroll)
        chat.remove_children()
        for m in self.session.messages:
            if m["role"] == "user" and m.get("content"):
                chat.mount(Static(f"你：{m['content']}", classes="msg-user"))
            elif m["role"] == "assistant" and m.get("content"):
                chat.mount(Markdown(m["content"], classes="msg-assistant"))
        chat.scroll_end(animate=False)
        self._status()

    def new_session(self, title: str = "新会话") -> None:
        self.session = self.store.create(title=title)
        self._make_agent()
        self.query_one("#chat", VerticalScroll).remove_children()
        self.refresh_sessions()
        self._status()

    # ---------- 危险命令确认（worker 线程调用，阻塞等 UI 回答） ----------

    def _confirm_dangerous(self, command: str) -> bool:
        done = threading.Event()
        result = {"ok": False}

        def on_answer(ok: bool | None) -> None:
            result["ok"] = bool(ok)
            done.set()

        self.call_from_thread(
            lambda: self.push_screen(ConfirmScreen(command), on_answer)
        )
        done.wait()
        return result["ok"]

    # ---------- 输入处理 ----------

    @on(Input.Submitted, "#input-bar")
    def on_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("!"):
            cmd = text[1:].strip()
            if cmd:
                self._chat_mount(Static(f"$ {cmd}", classes="msg-user"))
                self._chat_mount(Static(run_shell(cmd), classes="tool-card"))
            return
        cmd = parse_command(text)
        if cmd:
            self.handle_command(cmd)
            return
        self.send_message(text)

    @on(Input.Changed, "#search")
    def on_search(self, event: Input.Changed) -> None:
        self.refresh_sessions(keyword=event.value.strip())

    @on(ListView.Selected, "#session-list")
    def on_pick(self, event: ListView.Selected) -> None:
        if event.item.name:
            self.load_session(event.item.name)

    @on(Button.Pressed, "#new-btn")
    def on_new(self) -> None:
        self.new_session()

    def action_toggle_mode(self) -> None:
        if self.agent:
            self.agent.mode = Mode.THINK if self.agent.mode is Mode.ACT else Mode.ACT
            self._status()

    def action_new_session(self) -> None:
        self.new_session()

    def handle_command(self, cmd: Command) -> None:
        """斜杠命令（与 parse_command 配套的独立逻辑层）。"""
        if cmd.name == "mode" and cmd.arg:
            self.agent.mode = Mode.parse(cmd.arg)
        elif cmd.name == "provider" and cmd.arg in self.registry.names():
            self.provider = cmd.arg
            self.agent.client = self.registry.client(self.provider)
            self.agent.model = self.registry.default_model(self.provider)
        elif cmd.name == "model" and cmd.arg:
            self.agent.model = cmd.arg
        elif cmd.name == "new":
            self.new_session(title=cmd.arg or "新会话")
            return
        elif cmd.name == "search":
            self.query_one("#search", Input).value = cmd.arg
            return
        elif cmd.name == "help":
            self._chat_mount(Static(HELP_TEXT, classes="tool-card"))
            return
        else:
            self._chat_mount(Static("未知命令，/help 查看帮助", classes="tool-card"))
            return
        self._status()

    # ---------- 对话 ----------

    def _chat_mount(self, widget) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(widget)
        chat.scroll_end(animate=False)

    def send_message(self, text: str) -> None:
        self._chat_mount(Static(f"你：{text}", classes="msg-user"))
        self._cur_md = None
        self._cur_text = ""
        self._run_agent(text)

    @work(thread=True)
    def _run_agent(self, text: str) -> None:
        """worker 线程跑 agent，事件经 call_from_thread 回 UI 线程。"""
        for ev in self.agent.run_turn(text):
            self.call_from_thread(self._on_event, ev)
        self.call_from_thread(self._turn_done, text)

    def _on_event(self, ev) -> None:
        if ev.kind == "text_delta":
            self._cur_text += ev.data["delta"]
            if self._cur_md is None:
                self._cur_md = Markdown("", classes="msg-assistant")
                self._chat_mount(self._cur_md)
            self._cur_md.update(self._cur_text)
            self.query_one("#chat", VerticalScroll).scroll_end(animate=False)
        elif ev.kind == "tool_call":
            self._cur_tool = ToolCard(ev.data["tool"], ev.data["args"])
            self._chat_mount(self._cur_tool)
        elif ev.kind == "tool_result" and self._cur_tool:
            self._cur_tool.set_result(ev.data["result"])
            self._cur_tool = None

    def _turn_done(self, user_text: str) -> None:
        # 首轮自动命名
        if self.session and self.session.title == "新会话":
            self.store.rename(self.session.id, user_text[:20])
            self.session.title = user_text[:20]
            self.refresh_sessions()
        self._status()


def main() -> None:
    ChatApp().run()


if __name__ == "__main__":
    main()
