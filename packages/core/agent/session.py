"""多 session 管理：JSONL 存储 + 元数据索引 + 搜索。"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

SESSIONS_DIR = Path.home() / ".agent" / "sessions"


@dataclass
class Session:
    id: str
    title: str
    created_at: float
    updated_at: float
    messages: list = field(default_factory=list)


class SessionStore:
    """session 落盘：~/.agent/sessions/<id>.jsonl，索引 index.json。"""

    def __init__(self, root: Path = SESSIONS_DIR):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.jsonl"

    def _index_path(self) -> Path:
        return self.root / "index.json"

    def _read_index(self) -> dict:
        p = self._index_path()
        if not p.exists():
            return {}
        return json.loads(p.read_text())

    def _write_index(self, index: dict) -> None:
        self._index_path().write_text(json.dumps(index, ensure_ascii=False, indent=2))

    def create(self, title: str = "新会话") -> Session:
        now = time.time()
        s = Session(id=uuid.uuid4().hex[:8], title=title, created_at=now, updated_at=now)
        self._save_meta(s)
        self._path(s.id).touch()
        return s

    def _save_meta(self, s: Session) -> None:
        index = self._read_index()
        index[s.id] = {
            "title": s.title,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        }
        self._write_index(index)

    def list(self) -> list[Session]:
        """按最近更新排序返回全部 session（不含消息体）。"""
        metas = sorted(
            self._read_index().items(), key=lambda kv: kv[1]["updated_at"], reverse=True
        )
        return [
            Session(id=sid, title=m["title"], created_at=m["created_at"], updated_at=m["updated_at"])
            for sid, m in metas
        ]

    def load(self, session_id: str) -> Session:
        """加载 session 元数据 + 完整消息历史。"""
        meta = self._read_index()[session_id]
        messages = []
        p = self._path(session_id)
        if p.exists():
            for line in p.read_text().splitlines():
                if line.strip():
                    messages.append(json.loads(line))
        return Session(id=session_id, messages=messages, **meta)

    def append(self, session_id: str, message: dict) -> None:
        """追加一条消息并更新 updated_at。"""
        with open(self._path(session_id), "a") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")
        index = self._read_index()
        if session_id in index:
            index[session_id]["updated_at"] = time.time()
            self._write_index(index)

    def rename(self, session_id: str, title: str) -> None:
        index = self._read_index()
        index[session_id]["title"] = title
        self._write_index(index)

    def search(self, keyword: str) -> list[tuple[Session, str]]:
        """按标题+消息内容子串匹配，返回 (session, 命中的片段)。"""
        kw = keyword.lower()
        hits = []
        for s in self.list():
            if kw in s.title.lower():
                hits.append((s, s.title))
                continue
            p = self._path(s.id)
            if not p.exists():
                continue
            for line in p.read_text().splitlines():
                if kw in line.lower():
                    snippet = line.strip()[:120]
                    hits.append((s, snippet))
                    break
        return hits
