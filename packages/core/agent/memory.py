"""记忆系统：艾宾浩斯遗忘曲线 + 向量检索（sqlite-vec）+ 双层记忆。

- soft 记忆：R = e^(-t/S) 衰减，检索命中则强化 S *= 2.5，R<0.15 惰性遗忘
- hard 记忆：pinned，R 恒为 1，永不衰减
- 默认注入 7 天窗口，recall() 支持扩大窗口回溯
"""

import json
import math
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import numpy as np
import sqlite_vec
from fastembed import TextEmbedding

DB_PATH = Path.home() / ".agent" / "memory.db"
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIM = 384

# 艾宾浩斯参数
INIT_STABILITY = 86400.0      # S 初始 1 天（秒）
REINFORCE_FACTOR = 2.5        # 命中强化倍率
FORGET_THRESHOLD = 0.15       # soft 记忆 R 低于此值则遗忘
RECALL_THRESHOLD = 0.3        # 注入 prompt 的最低分
TOP_K = 5
DEFAULT_DAYS = 7
MERGE_SIM = 0.9               # 写入相似度超过此值则合并而非新增

# 硬记忆兜底：命中即强制 kind=hard（宁多勿少）
HARD_PATTERNS = re.compile(
    r"[~/]|\.(?:com|cn|io|dev|ai)\b|key|密钥|密码|端口|token|我决定|以后都|记住",
    re.IGNORECASE,
)

# 全局模型实例（懒加载，避免 import 时就下载模型）
_model = None


def _embedder() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(MODEL_NAME)
    return _model


def embed(texts: list[str]) -> np.ndarray:
    return np.array(list(_embedder().embed(texts)), dtype=np.float32)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


class NullMemory:
    """空实现：不存不取，作为默认占位。"""

    def read(self, query: str) -> str:
        return ""

    def write(self, items: list[dict], session_id: str = "") -> None:
        pass

    def recall(self, query: str, days: int | None = None,
               top_k: int = 5, reinforce: bool = True) -> list[str]:
        return []


class EbbinghausMemory:
    """双层记忆 + 艾宾浩斯衰减，SQLite 单文件存储。"""

    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False：FastAPI 线程池场景需要；用锁保证并发安全
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS memories(
                id TEXT PRIMARY KEY,
                content TEXT,
                kind TEXT,                 -- 'soft' | 'hard'
                created_at REAL,
                last_reviewed_at REAL,
                stability REAL,
                review_count INTEGER,
                session_id TEXT
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories USING vec0(
                id TEXT PRIMARY KEY,
                embedding float[{DIM}]
            );
        """)

    # ---------- 写入 ----------

    def add(self, items: list[dict], session_id: str = "") -> None:
        """写入记忆：{content, kind}，相似则合并强化，否则新增。"""
        if not items:
            return
        contents = [it["content"] for it in items]
        vecs = embed(contents)
        for it, vec in zip(items, vecs):
            kind = it.get("kind", "soft")
            if HARD_PATTERNS.search(it["content"]):
                kind = "hard"  # 关键词兜底
            dup = self._most_similar(vec)
            if dup and _cosine(vec, dup[1]) > MERGE_SIM:
                self._reinforce(dup[0])  # 已有相似记忆 → 强化
                continue
            mid = uuid.uuid4().hex[:12]
            now = time.time()
            self.conn.execute(
                "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?)",
                (mid, it["content"], kind, now, now, INIT_STABILITY, 0, session_id),
            )
            self.conn.execute(
                "INSERT INTO vec_memories(id, embedding) VALUES (?,?)",
                (mid, vec.tobytes()),
            )
        self.conn.commit()

    def _most_similar(self, vec: np.ndarray):
        rows = self.conn.execute(
            "SELECT id, embedding FROM vec_memories"
        ).fetchall()
        if not rows:
            return None
        best, best_sim = None, -1.0
        for rid, blob in rows:
            sim = _cosine(vec, np.frombuffer(blob, dtype=np.float32))
            if sim > best_sim:
                best, best_sim = (rid, np.frombuffer(blob, dtype=np.float32)), sim
        return best

    def _reinforce(self, mid: str) -> None:
        """复习强化：S 增大，更新复习时间。"""
        self.conn.execute(
            "UPDATE memories SET stability = stability * ?, "
            "review_count = review_count + 1, last_reviewed_at = ? WHERE id = ?",
            (REINFORCE_FACTOR, time.time(), mid),
        )
        self.conn.commit()

    # ---------- 读取 ----------

    def _candidates(self, days: int | None) -> list[dict]:
        """取窗口内记忆并计算当前保持率 R。"""
        now = time.time()
        sql = "SELECT id, content, kind, last_reviewed_at, stability FROM memories"
        args: tuple = ()
        if days is not None:
            sql += " WHERE created_at > ?"
            args = (now - days * 86400,)
        out = []
        for mid, content, kind, last, s in self.conn.execute(sql, args):
            r = 1.0 if kind == "hard" else math.exp(-(now - last) / s)
            out.append({"id": mid, "content": content, "kind": kind, "r": r})
        return out

    def recall(self, query: str, days: int | None = DEFAULT_DAYS,
               top_k: int = TOP_K, reinforce: bool = True) -> list[str]:
        """语义检索：score = sim × R，返回 top_k 条内容。"""
        cands = self._candidates(days)
        if not cands:
            return []
        qv = embed([query])[0]
        vecs = {
            rid: np.frombuffer(blob, dtype=np.float32)
            for rid, blob in self.conn.execute("SELECT id, embedding FROM vec_memories")
        }
        scored = [
            (c, _cosine(qv, vecs[c["id"]]) * c["r"])
            for c in cands if c["id"] in vecs
        ]
        scored = [x for x in scored if x[1] >= RECALL_THRESHOLD]
        scored.sort(key=lambda x: x[1], reverse=True)
        hits = scored[:top_k]
        if reinforce:
            for c, _ in hits:
                self._reinforce(c["id"])
        return [c["content"] for c, _ in hits]

    # ---------- Memory 接口 ----------

    def read(self, query: str) -> str:
        """轮开始：注入 7 天窗口内相关记忆，并惰性遗忘。"""
        self._forget()
        hits = self.recall(query, days=DEFAULT_DAYS)
        if not hits:
            return ""
        return "相关记忆：\n" + "\n".join(f"- {h}" for h in hits)

    def write(self, items: list[dict], session_id: str = "") -> None:
        """轮结束：落库（由 loop 完成 LLM 抽取后调用）。"""
        self.add(items, session_id)

    # ---------- 遗忘 ----------

    def _forget(self) -> None:
        """惰性遗忘：删除 R 低于阈值的 soft 记忆。"""
        doomed = [
            c["id"] for c in self._candidates(days=None)
            if c["kind"] == "soft" and c["r"] < FORGET_THRESHOLD
        ]
        for mid in doomed:
            self.conn.execute("DELETE FROM memories WHERE id = ?", (mid,))
            self.conn.execute("DELETE FROM vec_memories WHERE id = ?", (mid,))
        if doomed:
            self.conn.commit()

    def stats(self) -> dict:
        n_soft, n_hard = self.conn.execute(
            "SELECT COUNT(*) FILTER (WHERE kind='soft'), "
            "COUNT(*) FILTER (WHERE kind='hard') FROM memories"
        ).fetchone()
        return {"soft": n_soft, "hard": n_hard}
