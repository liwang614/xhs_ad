from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class InteractionRecord:
    feed_id: str
    keyword: str
    comment_content: str
    is_liked: bool
    created_at: str


class HistoryStore:
    def __init__(self, db_path: str = "data/history.db") -> None:
        self.db_path = db_path
        self._ensure_directory(db_path)
        self._conn = sqlite3.connect(db_path)
        self._init_schema()

    def __enter__(self) -> "HistoryStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def check_duplicate(self, feed_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM interactions WHERE feed_id = ? LIMIT 1",
            (feed_id,),
        )
        return cur.fetchone() is not None

    def log_action(self, record: InteractionRecord) -> bool:
        cur = self._conn.execute(
            """
            INSERT OR IGNORE INTO interactions
            (feed_id, keyword, comment_content, is_liked, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                record.feed_id,
                record.keyword,
                record.comment_content,
                1 if record.is_liked else 0,
                record.created_at,
            ),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def count_all(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM interactions")
        row = cur.fetchone()
        if row is None:
            return 0
        return int(row[0])

    def generate_report(self, processed: int, skipped: int, failed: int) -> str:
        return f"本次处理(成功) {processed} 条，跳过 {skipped} 条，失败 {failed} 条"

    def _ensure_directory(self, path: str) -> None:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS interactions (
                feed_id TEXT PRIMARY KEY,
                keyword TEXT,
                comment_content TEXT,
                is_liked INTEGER,
                created_at TEXT
            )
            """
        )
        self._conn.commit()
