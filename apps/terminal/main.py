"""Terminal 前端：REPL + 斜杠命令 + 启动时 session 选择。"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "core"))

from agent.loop import Agent
from agent.memory import EbbinghausMemory
from agent.modes import Mode
from agent.providers import ProviderRegistry
from agent.session import SessionStore
from agent.tools import run_shell

HELP = """命令：
  /mode think|act   切换模式
  /provider <名>    切换供应商
  /model <名>       切换模型
  /sessions         列出并切换会话
  /new [标题]       新建会话
  /search <关键词>  搜索历史会话
  /help             帮助
  !<命令>           直接执行 shell（不经过 LLM）
  exit/quit         退出
"""


def fmt_time(ts: float) -> str:
    return time.strftime("%m-%d %H:%M", time.localtime(ts))


def pick_session(store: SessionStore):
    """启动/切换时列出 session，支持选择或新建。"""
    sessions = store.list()
    if sessions:
        print("会话列表：")
        for i, s in enumerate(sessions, 1):
            print(f"  {i}. [{s.id}] {s.title}  ({fmt_time(s.updated_at)})")
        print("输入序号选择，或直接回车新建：")
    else:
        print("暂无历史会话，回车新建：")
    choice = input("session> ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(sessions):
        return store.load(sessions[int(choice) - 1].id)
    return store.create(title=choice or "新会话")


def make_agent(registry: ProviderRegistry, provider: str, session, store: SessionStore,
               memory: EbbinghausMemory) -> Agent:
    return Agent(
        client=registry.client(provider),
        model=registry.default_model(provider),
        messages=session.messages or None,
        session_id=session.id,
        memory=memory,
        on_message=lambda m: store.append(session.id, m),
        # 危险命令确认：stdin 询问，y 才执行
        confirm=lambda cmd: input(f"⚠️ 危险命令，确认执行？ {cmd} [y/N] ").strip().lower() == "y",
    )


def main() -> None:
    store = SessionStore()
    registry = ProviderRegistry()
    provider = registry.names()[0]
    memory = EbbinghausMemory()

    session = pick_session(store)
    agent = make_agent(registry, provider, session, store, memory)
    print(f"会话 [{session.id}] {session.title} | 供应商 {provider} | 模型 {agent.model} | 模式 {agent.mode.value}")
    print(HELP)

    while True:
        try:
            user = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user:
            continue
        if user in ("exit", "quit"):
            break

        # ! 前缀：直接执行 shell，不经过 LLM
        if user.startswith("!"):
            cmd = user[1:].strip()
            if cmd:
                print(run_shell(cmd))
            continue

        if user.startswith("/"):
            parts = user.split(maxsplit=1)
            cmd, arg = parts[0], parts[1] if len(parts) > 1 else ""
            if cmd == "/mode" and arg:
                agent.mode = Mode.parse(arg)
                print(f"模式 → {agent.mode.value}")
            elif cmd == "/provider" and arg in registry.names():
                provider = arg
                agent.client = registry.client(provider)
                agent.model = registry.default_model(provider)
                print(f"供应商 → {provider}，模型 → {agent.model}")
            elif cmd == "/model" and arg:
                agent.model = arg
                print(f"模型 → {agent.model}")
            elif cmd == "/sessions":
                session = pick_session(store)
                agent = make_agent(registry, provider, session, store, memory)
                agent.mode = Mode.ACT
                print(f"切换到会话 [{session.id}] {session.title}")
            elif cmd == "/new":
                session = store.create(title=arg or "新会话")
                agent = make_agent(registry, provider, session, store, memory)
                print(f"新会话 [{session.id}] {session.title}")
            elif cmd == "/search" and arg:
                for s, snippet in store.search(arg):
                    print(f"  [{s.id}] {s.title} ({fmt_time(s.updated_at)})\n    {snippet}")
            elif cmd == "/help":
                print(HELP)
            else:
                print("未知命令，/help 查看帮助")
            continue

        titled = False
        streaming_text = False
        for ev in agent.run_turn(user):
            if ev.kind == "text_delta":
                print(ev.data["delta"], end="", flush=True)  # 流式逐字输出
                streaming_text = True
            elif ev.kind == "tool_call":
                if streaming_text:
                    print()
                    streaming_text = False
                print(f"$ {ev.data['args'].get('command', ev.data['args'])}")
            elif ev.kind == "done":
                if streaming_text:
                    print()
        # 首轮自动用首句作为会话标题
        if not titled and session.title == "新会话":
            store.rename(session.id, user[:20])
            session.title = user[:20]
            titled = True


if __name__ == "__main__":
    if "--plain" in sys.argv:
        main()  # 纯文本 REPL 回退
    else:
        from tui import main as tui_main

        tui_main()
