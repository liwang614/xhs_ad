from __future__ import annotations

from dataclasses import dataclass
import os

import pymysql


@dataclass(frozen=True)
class InteractionRecord:
    feed_id: str
    keyword: str
    comment_content: str
    is_liked: bool
    created_at: str


class HistoryStore:
    def __init__(self) -> None:
        self._table = os.getenv("MYSQL_HISTORY_TABLE", "interactions")
        self._conn = pymysql.connect(
            host=os.getenv("MYSQL_DB_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_DB_PORT", "3306")),
            user=os.getenv("MYSQL_DB_USER", "root"),
            password=os.getenv("MYSQL_DB_PWD", ""),
            database=os.getenv("MYSQL_DB_NAME", "media_crawler"),
            charset="utf8mb4",
            autocommit=False,
        )
        self._init_schema()

    def __enter__(self) -> "HistoryStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def check_duplicate(self, feed_id: str) -> bool:
        sql = f"SELECT 1 FROM `{self._table}` WHERE feed_id = %s LIMIT 1"
        with self._conn.cursor() as cur:
            cur.execute(sql, (feed_id,))
            return cur.fetchone() is not None

    def log_action(self, record: InteractionRecord) -> bool:
        sql = f"""
        INSERT IGNORE INTO `{self._table}`
        (feed_id, keyword, comment_content, is_liked, created_at)
        VALUES (%s, %s, %s, %s, %s)
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    record.feed_id,
                    record.keyword,
                    record.comment_content,
                    1 if record.is_liked else 0,
                    record.created_at,
                ),
            )
            inserted = cur.rowcount == 1
        self._conn.commit()
        return inserted

    def count_all(self) -> int:
        sql = f"SELECT COUNT(*) FROM `{self._table}`"
        with self._conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            if row is None:
                return 0
            return int(row[0])

    def generate_report(self, processed: int, skipped: int, failed: int) -> str:
        return f"本次处理(成功) {processed} 条，跳过 {skipped} 条，失败 {failed} 条"

    def _init_schema(self) -> None:
        sql = f"""
        CREATE TABLE IF NOT EXISTS `{self._table}` (
            feed_id VARCHAR(64) PRIMARY KEY,
            keyword VARCHAR(255),
            comment_content TEXT,
            is_liked TINYINT(1),
            created_at DATETIME
        ) CHARACTER SET utf8mb4
        """
        with self._conn.cursor() as cur:
            cur.execute(sql)
        self._conn.commit()
