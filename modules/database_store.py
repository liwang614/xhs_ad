from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
import re
from typing import List, Optional, Sequence, Set, Tuple

import pymysql

HELP_POST_COLUMN_SQL = "TINYINT NULL COMMENT 'AI判断:是否求助帖(1是0否)'"
GENERATED_COMMENT_COLUMN = "generated_comment_content"
LEGACY_SENT_COMMENT_COLUMN = "sent_comment_content"
NOTE_COMMENT_TABLE = "xhs_note_comment"

# --- 商业机会分析新增字段 ---
ANALYSIS_COLUMNS = {
    "opportunity_type": "VARCHAR(50) NULL COMMENT '机会类型(solution_request/none)'",
    "opportunity_summary": "TEXT NULL COMMENT '机会摘要'",
    "demand_reason": "TEXT NULL COMMENT '需求判定理由'",
    "lead_score": "INT NULL COMMENT '线索评分(0-100)'",
    "manual_reply_suggestion": "TEXT NULL COMMENT '建议人工回复话术'",
    "analysis_status": "VARCHAR(20) NULL COMMENT '分析状态(done/failed)'",
    "analyzed_at": "DATETIME NULL COMMENT '分析完成时间'",
    "follow_up_status": "VARCHAR(20) NULL DEFAULT 'pending' COMMENT '跟进状态(pending/contacted/ignored)'",
}

COMMENTER_UID_CANDIDATES = ("user_id", "uid", "author_id", "comment_user_id")


@dataclass(frozen=True)
class NoteRecord:
    id: int
    feed_id: str
    title: str
    content: str
    is_duplicate: int
    is_help_post: Optional[int]


@dataclass(frozen=True)
class InteractionRecord:
    feed_id: str
    keyword: str
    comment_content: str
    is_liked: bool
    is_duplicate: int
    created_at: str
    note_id: int = 0


@dataclass(frozen=True)
class PendingAnalysisRecord:
    table_name: str
    row_id: int
    title: str
    content: str
    commenter_uid: str


@dataclass
class AnalysisResult:
    is_help_post: int
    opportunity_type: str
    opportunity_summary: str
    demand_reason: str
    lead_score: int
    manual_reply_suggestion: str
    commenter_uid: str


@dataclass(frozen=True)
class HelpCommentGenerateRecord:
    table_name: str
    row_id: int
    comment_id: str
    feed_id: str
    xsec_token: str
    title: str
    content: str
    generated_comment_content: str


@dataclass(frozen=True)
class HelpCommentReplyRecord:
    table_name: str
    row_id: int
    comment_id: str
    feed_id: str
    xsec_token: str
    content: str


class DatabaseStore:
    def __init__(self) -> None:
        self._note_table = self._validate_table_name(
            os.getenv("MYSQL_NOTE_TABLE", "xhs_note"),
            "MYSQL_NOTE_TABLE",
        )
        self._interaction_table = self._validate_table_name(
            os.getenv("MYSQL_HISTORY_TABLE", "interactions"),
            "MYSQL_HISTORY_TABLE",
        )
        self._note_comment_table = self._validate_table_name(
            os.getenv("MYSQL_NOTE_COMMENT_TABLE", NOTE_COMMENT_TABLE),
            "MYSQL_NOTE_COMMENT_TABLE",
        )
        self._db_name = os.getenv("MYSQL_DB_NAME", "media_crawler")
        self._conn = pymysql.connect(
            host=os.getenv("MYSQL_DB_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_DB_PORT", "3306")),
            user=os.getenv("MYSQL_DB_USER", "root"),
            password=os.getenv("MYSQL_DB_PWD", "root"),
            database=self._db_name,
            charset="utf8mb4",
            autocommit=False,
        )
        self._init_schema()

    def __enter__(self) -> "DatabaseStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        interaction_sql = f"""
        CREATE TABLE IF NOT EXISTS `{self._interaction_table}` (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            feed_id VARCHAR(64) NOT NULL,
            keyword VARCHAR(255),
            comment_content TEXT,
            is_liked TINYINT(1) NOT NULL DEFAULT 0,
            is_duplicate TINYINT(1) NOT NULL DEFAULT 0,
            created_at DATETIME,
            KEY idx_feed_id (feed_id)
        ) CHARACTER SET utf8mb4
        """
        with self._conn.cursor() as cur:
            cur.execute(interaction_sql)

            # Keep schema migration compatible with older MySQL versions.
            self._ensure_column(cur, self._interaction_table, "is_duplicate", "TINYINT(1) NOT NULL DEFAULT 0")
            self._ensure_column(cur, self._note_table, "is_duplicate", "TINYINT(1) NOT NULL DEFAULT 0")
            self._ensure_column(
                cur,
                self._note_table,
                "is_help_post",
                HELP_POST_COLUMN_SQL,
            )
            self._ensure_note_comment_schema(cur)
            self._ensure_analysis_columns(cur)
        self._conn.commit()

    def _ensure_column(self, cur: pymysql.cursors.Cursor, table_name: str, column_name: str, column_sql: str) -> None:
        exists_sql = """
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
        LIMIT 1
        """
        cur.execute(exists_sql, (self._db_name, table_name, column_name))
        if cur.fetchone() is not None:
            return
        cur.execute(f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {column_sql}")

    def _table_exists(self, cur: pymysql.cursors.Cursor, table_name: str) -> bool:
        sql = """
        SELECT 1
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
        LIMIT 1
        """
        cur.execute(sql, (self._db_name, table_name))
        return cur.fetchone() is not None

    def _get_table_column_order(self, table_name: str) -> List[str]:
        sql = """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
        ORDER BY ORDINAL_POSITION
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (self._db_name, table_name))
            rows = cur.fetchall()
        return [str(row[0]) for row in rows]

    @staticmethod
    def _is_note_comment_layout_aligned(column_order: Sequence[str]) -> bool:
        try:
            content_idx = column_order.index("content")
        except ValueError:
            return False
        expected = ("is_help_post", GENERATED_COMMENT_COLUMN)
        for offset, column_name in enumerate(expected, start=1):
            idx = content_idx + offset
            if idx >= len(column_order) or column_order[idx] != column_name:
                return False
        return True

    def _ensure_note_comment_schema(self, cur: pymysql.cursors.Cursor) -> None:
        if not self._table_exists(cur, self._note_comment_table):
            return

        self._ensure_column(cur, self._note_comment_table, "is_help_post", HELP_POST_COLUMN_SQL)
        self._ensure_column(
            cur,
            self._note_comment_table,
            GENERATED_COMMENT_COLUMN,
            "TEXT NULL COMMENT '评论文案(单条)'",
        )

        columns = self._get_table_columns(self._note_comment_table)
        if LEGACY_SENT_COMMENT_COLUMN in columns:
            # Merge legacy sent column into single comment column before dropping.
            cur.execute(
                f"""
                UPDATE `{self._note_comment_table}`
                SET `{GENERATED_COMMENT_COLUMN}` = CASE
                    WHEN (`{GENERATED_COMMENT_COLUMN}` IS NULL OR `{GENERATED_COMMENT_COLUMN}` = '')
                         AND `{LEGACY_SENT_COMMENT_COLUMN}` IS NOT NULL
                         AND `{LEGACY_SENT_COMMENT_COLUMN}` <> ''
                    THEN `{LEGACY_SENT_COMMENT_COLUMN}`
                    ELSE `{GENERATED_COMMENT_COLUMN}`
                END
                """
            )
            cur.execute(f"ALTER TABLE `{self._note_comment_table}` DROP COLUMN `{LEGACY_SENT_COMMENT_COLUMN}`")

        column_order = self._get_table_column_order(self._note_comment_table)
        if "content" not in column_order:
            return
        if self._is_note_comment_layout_aligned(column_order):
            return

        cur.execute(
            f"ALTER TABLE `{self._note_comment_table}` "
            f"MODIFY COLUMN `is_help_post` {HELP_POST_COLUMN_SQL} AFTER `content`"
        )
        cur.execute(
            f"ALTER TABLE `{self._note_comment_table}` "
            f"MODIFY COLUMN `{GENERATED_COMMENT_COLUMN}` TEXT NULL COMMENT '评论文案(单条)' AFTER `is_help_post`"
        )

    @staticmethod
    def _validate_table_name(table_name: str, field_name: str) -> str:
        text = (table_name or "").strip()
        if not text:
            raise ValueError(f"{field_name} is empty")
        if not re.fullmatch(r"[A-Za-z0-9_]+", text):
            raise ValueError(f"{field_name} contains invalid table name: {table_name}")
        return text

    def _resolve_note_table(self, table_name: Optional[str]) -> str:
        if table_name is None:
            return self._note_table
        return self._validate_table_name(table_name, "table_name")

    @staticmethod
    def _normalize_row_ids(row_ids: Optional[Sequence[int]]) -> List[int]:
        if not row_ids:
            return []
        out: List[int] = []
        for item in row_ids:
            try:
                row_id = int(item)
            except (TypeError, ValueError):
                continue
            if row_id <= 0:
                continue
            if row_id not in out:
                out.append(row_id)
        return out

    def _ensure_analysis_columns(self, cur: pymysql.cursors.Cursor) -> None:
        for table_name in (self._note_table, self._note_comment_table):
            if not self._table_exists(cur, table_name):
                continue
            self._ensure_analysis_columns_for_table(cur, table_name)

    def _ensure_analysis_columns_for_table(self, cur: pymysql.cursors.Cursor, table_name: str) -> None:
        for col_name, col_sql in ANALYSIS_COLUMNS.items():
            self._ensure_column(cur, table_name, col_name, col_sql)

    def _ensure_analysis_schema(self, table_name: str) -> None:
        with self._conn.cursor() as cur:
            if not self._table_exists(cur, table_name):
                return
            self._ensure_analysis_columns_for_table(cur, table_name)
        self._conn.commit()

    def fetch_pending_analysis(
        self,
        limit: int,
        *,
        table_name: Optional[str] = None,
        only_unanalyzed: bool = True,
    ) -> List[PendingAnalysisRecord]:
        note_table = self._resolve_note_table(table_name)
        self._ensure_analysis_schema(note_table)
        columns = self._get_table_columns(note_table)
        if "id" not in columns:
            raise ValueError(f"table '{note_table}' has no id column")

        title_col = self._pick_existing_column(columns, ("title", "note_title"))
        content_col = self._pick_existing_column(columns, ("desc", "content", "text", "comment", "body"))
        uid_col = self._pick_existing_column(columns, COMMENTER_UID_CANDIDATES)

        title_expr = f"`{title_col}`" if title_col else "''"
        content_expr = f"`{content_col}`" if content_col else "''"
        uid_expr = f"`{uid_col}`" if uid_col else "''"

        where = "analysis_status IS NULL" if only_unanalyzed else "1=1"
        sql = f"""
        SELECT id, {title_expr}, {content_expr}, {uid_expr}
        FROM `{note_table}`
        WHERE {where}
        ORDER BY id ASC
        LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()

        out: List[PendingAnalysisRecord] = []
        for row in rows:
            out.append(PendingAnalysisRecord(
                table_name=note_table,
                row_id=int(row[0]),
                title=str(row[1] or "").strip(),
                content=str(row[2] or "").strip(),
                commenter_uid=str(row[3] or "").strip(),
            ))
        return out

    def write_analysis_result(
        self,
        row_id: int,
        result: AnalysisResult,
        *,
        table_name: Optional[str] = None,
    ) -> None:
        note_table = self._resolve_note_table(table_name)
        self._ensure_analysis_schema(note_table)
        sql = f"""
        UPDATE `{note_table}`
        SET is_help_post=%s,
            opportunity_type=%s,
            opportunity_summary=%s,
            demand_reason=%s,
            lead_score=%s,
            manual_reply_suggestion=%s,
            analysis_status='done',
            analyzed_at=%s
        WHERE id=%s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (
                result.is_help_post,
                result.opportunity_type,
                result.opportunity_summary,
                result.demand_reason,
                result.lead_score,
                result.manual_reply_suggestion,
                self.now_text(),
                row_id,
            ))
        self._conn.commit()

    def mark_analysis_failed(
        self,
        row_id: int,
        *,
        table_name: Optional[str] = None,
    ) -> None:
        note_table = self._resolve_note_table(table_name)
        self._ensure_analysis_schema(note_table)
        sql = f"""
        UPDATE `{note_table}`
        SET analysis_status='failed', analyzed_at=%s
        WHERE id=%s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (self.now_text(), row_id))
        self._conn.commit()

    def update_follow_up_status(
        self,
        row_id: int,
        status: str,
        *,
        table_name: Optional[str] = None,
    ) -> None:
        if status not in ("pending", "contacted", "ignored"):
            raise ValueError(f"invalid follow_up_status: {status}")
        note_table = self._resolve_note_table(table_name)
        self._ensure_analysis_schema(note_table)
        sql = f"UPDATE `{note_table}` SET follow_up_status=%s WHERE id=%s"
        with self._conn.cursor() as cur:
            cur.execute(sql, (status, row_id))
        self._conn.commit()

    def ensure_help_post_column(self, table_name: Optional[str] = None) -> str:
        note_table = self._resolve_note_table(table_name)
        with self._conn.cursor() as cur:
            self._ensure_column(
                cur,
                note_table,
                "is_help_post",
                HELP_POST_COLUMN_SQL,
            )
        self._conn.commit()
        return note_table

    def ensure_generated_comment_column(self, table_name: Optional[str] = None) -> str:
        note_table = self._resolve_note_table(table_name)
        with self._conn.cursor() as cur:
            self._ensure_column(
                cur,
                note_table,
                GENERATED_COMMENT_COLUMN,
                "TEXT NULL COMMENT '评论文案(单条)'",
            )
        self._conn.commit()
        return note_table

    def _get_table_columns(self, table_name: str) -> Set[str]:
        sql = """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (self._db_name, table_name))
            rows = cur.fetchall()
        return {str(row[0]) for row in rows}

    @staticmethod
    def _pick_existing_column(columns: Set[str], candidates: Sequence[str]) -> Optional[str]:
        for name in candidates:
            if name in columns:
                return name
        return None

    def count_all_interactions(self) -> int:
        sql = f"SELECT COUNT(*) FROM `{self._interaction_table}`"
        with self._conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            if row is None:
                return 0
            return int(row[0])

    def search_notes(self, keyword: str, limit: int = 20) -> List[NoteRecord]:
        columns = self._get_table_columns(self._note_table)
        if "id" not in columns:
            raise ValueError(f"table '{self._note_table}' has no id column")

        feed_id_col = self._pick_existing_column(columns, ("feed_id", "note_id", "target_id", "item_id", "id"))
        if feed_id_col is None:
            raise ValueError(
                f"table '{self._note_table}' has no usable id column; expected one of "
                "feed_id/note_id/target_id/item_id/id"
            )

        title_col = self._pick_existing_column(columns, ("title", "note_title"))
        content_col = self._pick_existing_column(columns, ("desc", "content", "text", "comment", "body"))
        if title_col is None and content_col is None:
            raise ValueError(
                f"table '{self._note_table}' has no searchable text columns; expected one of "
                "title/note_title/desc/content/text/comment/body"
            )

        title_expr = f"`{title_col}`" if title_col is not None else "''"
        content_expr = f"`{content_col}`" if content_col is not None else "''"
        is_duplicate_expr = "`is_duplicate`" if "is_duplicate" in columns else "0"
        is_help_post_expr = "`is_help_post`" if "is_help_post" in columns else "NULL"

        where_parts: List[str] = []
        pattern = f"%{keyword}%"
        params: List[object] = []
        if title_col is not None:
            where_parts.append(f"`{title_col}` LIKE %s")
            params.append(pattern)
        if content_col is not None and content_col != title_col:
            where_parts.append(f"`{content_col}` LIKE %s")
            params.append(pattern)
        if not where_parts:
            return []

        where_clause = " OR ".join(where_parts)
        sql = f"""
        SELECT
            id,
            `{feed_id_col}` AS feed_id,
            {title_expr} AS title_text,
            {content_expr} AS content_text,
            {is_duplicate_expr} AS is_duplicate,
            {is_help_post_expr} AS is_help_post
        FROM `{self._note_table}`
        WHERE ({where_clause})
        ORDER BY id DESC
        LIMIT %s
        """
        params.append(limit)
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        result: List[NoteRecord] = []
        for row in rows:
            note_id = int(row[0]) if row[0] is not None else 0
            feed_id = str(row[1]).strip() if row[1] is not None else ""
            title = str(row[2]).strip() if row[2] is not None else ""
            content = str(row[3]).strip() if row[3] is not None else ""
            is_duplicate = int(row[4] or 0)
            is_help_post = None if row[5] is None else int(row[5])
            if not feed_id:
                continue
            result.append(
                NoteRecord(
                    id=note_id,
                    feed_id=feed_id,
                    title=title,
                    content=content,
                    is_duplicate=is_duplicate,
                    is_help_post=is_help_post,
                )
            )
        return result

    def fetch_pending_help_posts(self, limit: int, table_name: Optional[str] = None) -> List[Tuple[int, str, str]]:
        note_table = self.ensure_help_post_column(table_name)
        columns = self._get_table_columns(note_table)
        if "id" not in columns:
            raise ValueError(f"table '{note_table}' has no id column")

        title_col = self._pick_existing_column(columns, ("title", "note_title"))
        content_col = self._pick_existing_column(columns, ("desc", "content", "text", "comment", "body"))
        # If no dedicated content column exists, fall back to title text.
        if content_col is None:
            content_col = title_col

        if title_col is None and content_col is None:
            raise ValueError(
                f"table '{note_table}' has no usable text columns; expected one of "
                "title/note_title/desc/content/text/comment/body"
            )

        title_expr = f"`{title_col}`" if title_col is not None else "''"
        content_expr = f"`{content_col}`" if content_col is not None else "''"
        sql = f"""
        SELECT id, {title_expr} AS title_text, {content_expr} AS content_text
        FROM `{note_table}`
        WHERE is_help_post IS NULL
        ORDER BY id ASC
        LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (limit,))
            rows: Sequence[Tuple[object, object, object]] = cur.fetchall()

        out: List[Tuple[int, str, str]] = []
        for row in rows:
            out.append(
                (
                    int(row[0]),
                    str(row[1] or ""),
                    str(row[2] or ""),
                )
            )
        return out

    def fetch_help_comments_for_generation(
        self,
        limit: int,
        *,
        table_name: str,
        overwrite_existing: bool = False,
        row_ids: Optional[Sequence[int]] = None,
    ) -> List[HelpCommentGenerateRecord]:
        note_table = self.ensure_help_post_column(table_name)
        self.ensure_generated_comment_column(note_table)
        columns = self._get_table_columns(note_table)
        if "id" not in columns:
            raise ValueError(f"table '{note_table}' has no id column")

        title_col = self._pick_existing_column(columns, ("title", "note_title"))
        content_col = self._pick_existing_column(columns, ("desc", "content", "text", "comment", "body"))
        if title_col is None and content_col is None:
            raise ValueError(
                f"table '{note_table}' has no usable text columns; expected one of "
                "title/note_title/desc/content/text/comment/body"
            )
        comment_id_col = self._pick_existing_column(columns, ("comment_id",))
        feed_id_col = self._pick_existing_column(columns, ("feed_id", "note_id", "target_id", "item_id"))
        xsec_token_col = self._pick_existing_column(columns, ("xsec_token",))

        title_expr = f"`{title_col}`" if title_col is not None else "''"
        content_expr = f"`{content_col}`" if content_col is not None else "''"
        comment_id_expr = f"`{comment_id_col}`" if comment_id_col is not None else "''"
        feed_id_expr = f"`{feed_id_col}`" if feed_id_col is not None else "''"
        xsec_token_expr = f"`{xsec_token_col}`" if xsec_token_col is not None else "''"

        where_parts: List[str] = ["is_help_post=1"]
        params: List[object] = []
        if not overwrite_existing:
            where_parts.append(f"(`{GENERATED_COMMENT_COLUMN}` IS NULL OR `{GENERATED_COMMENT_COLUMN}`='')")

        normalized_ids = self._normalize_row_ids(row_ids)
        if normalized_ids:
            placeholders = ", ".join(["%s"] * len(normalized_ids))
            where_parts.append(f"id IN ({placeholders})")
            params.extend(normalized_ids)

        sql = f"""
        SELECT
            id,
            {comment_id_expr} AS comment_id,
            {feed_id_expr} AS feed_id,
            {xsec_token_expr} AS xsec_token,
            {title_expr} AS title_text,
            {content_expr} AS content_text,
            `{GENERATED_COMMENT_COLUMN}` AS generated_content
        FROM `{note_table}`
        WHERE {" AND ".join(where_parts)}
        ORDER BY id ASC
        LIMIT %s
        """
        params.append(limit)
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows: Sequence[Tuple[object, object, object, object, object, object, object]] = cur.fetchall()

        out: List[HelpCommentGenerateRecord] = []
        for row in rows:
            out.append(
                HelpCommentGenerateRecord(
                    table_name=note_table,
                    row_id=int(row[0]),
                    comment_id=str(row[1] or "").strip(),
                    feed_id=str(row[2] or "").strip(),
                    xsec_token=str(row[3] or "").strip(),
                    title=str(row[4] or "").strip(),
                    content=str(row[5] or "").strip(),
                    generated_comment_content=str(row[6] or "").strip(),
                )
            )
        return out

    def update_generated_comment(self, row_id: int, generated_comment_content: str, *, table_name: str) -> None:
        note_table = self.ensure_generated_comment_column(table_name)
        sql = f"UPDATE `{note_table}` SET `{GENERATED_COMMENT_COLUMN}`=%s WHERE id=%s"
        with self._conn.cursor() as cur:
            cur.execute(sql, (generated_comment_content, row_id))
        self._conn.commit()

    def fetch_help_comments_for_reply(
        self,
        limit: int,
        *,
        table_name: str,
        row_ids: Optional[Sequence[int]] = None,
    ) -> List[HelpCommentReplyRecord]:
        note_table = self.ensure_help_post_column(table_name)
        self.ensure_generated_comment_column(note_table)
        columns = self._get_table_columns(note_table)
        if "id" not in columns:
            raise ValueError(f"table '{note_table}' has no id column")

        comment_id_col = self._pick_existing_column(columns, ("comment_id",))
        feed_id_col = self._pick_existing_column(columns, ("feed_id", "note_id", "target_id", "item_id"))
        xsec_token_col = self._pick_existing_column(columns, ("xsec_token",))
        comment_id_expr = f"`{comment_id_col}`" if comment_id_col is not None else "''"
        feed_id_expr = f"`{feed_id_col}`" if feed_id_col is not None else "''"
        xsec_token_expr = f"`{xsec_token_col}`" if xsec_token_col is not None else "''"

        where_parts: List[str] = [
            "is_help_post=1",
            f"`{GENERATED_COMMENT_COLUMN}` IS NOT NULL",
            f"`{GENERATED_COMMENT_COLUMN}`<>''",
        ]
        params: List[object] = []
        normalized_ids = self._normalize_row_ids(row_ids)
        if normalized_ids:
            placeholders = ", ".join(["%s"] * len(normalized_ids))
            where_parts.append(f"id IN ({placeholders})")
            params.extend(normalized_ids)

        sql = f"""
        SELECT
            id,
            {comment_id_expr} AS comment_id,
            {feed_id_expr} AS feed_id,
            {xsec_token_expr} AS xsec_token,
            `{GENERATED_COMMENT_COLUMN}` AS generated_content
        FROM `{note_table}`
        WHERE {" AND ".join(where_parts)}
        ORDER BY id ASC
        LIMIT %s
        """
        params.append(limit)
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows: Sequence[Tuple[object, object, object, object, object]] = cur.fetchall()

        out: List[HelpCommentReplyRecord] = []
        for row in rows:
            out.append(
                HelpCommentReplyRecord(
                    table_name=note_table,
                    row_id=int(row[0]),
                    comment_id=str(row[1] or "").strip(),
                    feed_id=str(row[2] or "").strip(),
                    xsec_token=str(row[3] or "").strip(),
                    content=str(row[4] or "").strip(),
                )
            )
        return out

    def update_help_post(self, row_id: int, is_help_post: int, table_name: Optional[str] = None) -> None:
        note_table = self._resolve_note_table(table_name)
        sql = f"UPDATE `{note_table}` SET is_help_post=%s WHERE id=%s"
        with self._conn.cursor() as cur:
            cur.execute(sql, (is_help_post, row_id))
        self._conn.commit()

    def is_duplicate_feed(self, feed_id: str) -> bool:
        sql = f"SELECT COUNT(*) FROM `{self._note_table}` WHERE feed_id=%s"
        with self._conn.cursor() as cur:
            cur.execute(sql, (feed_id,))
            row = cur.fetchone()
            count = int(row[0]) if row else 0
        return count > 1

    def mark_note_duplicate(self, note_id: int, is_duplicate: bool) -> None:
        sql = f"UPDATE `{self._note_table}` SET is_duplicate=%s WHERE id=%s"
        with self._conn.cursor() as cur:
            cur.execute(sql, (1 if is_duplicate else 0, note_id))
        self._conn.commit()

    def check_duplicate_processed(self, feed_id: str) -> bool:
        sql = f"SELECT 1 FROM `{self._interaction_table}` WHERE feed_id=%s LIMIT 1"
        with self._conn.cursor() as cur:
            cur.execute(sql, (feed_id,))
            return cur.fetchone() is not None

    def log_action(self, record: InteractionRecord) -> bool:
        sql = f"""
        INSERT INTO `{self._interaction_table}`
        (feed_id, keyword, comment_content, is_liked, is_duplicate, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    record.feed_id,
                    record.keyword,
                    record.comment_content,
                    1 if record.is_liked else 0,
                    1 if record.is_duplicate else 0,
                    record.created_at,
                ),
            )
            inserted = cur.rowcount == 1
            if inserted:
                self._sync_comment_payload(cur, record)
        self._conn.commit()
        return inserted

    def _sync_comment_payload(self, cur: pymysql.cursors.Cursor, record: InteractionRecord) -> None:
        if not self._table_exists(cur, self._note_comment_table):
            return

        payload = (record.comment_content or "").strip()

        columns = self._get_table_columns(self._note_comment_table)
        if GENERATED_COMMENT_COLUMN not in columns:
            # Ensure migration can self-heal if xhs_note_comment appears after startup.
            self._ensure_note_comment_schema(cur)
            columns = self._get_table_columns(self._note_comment_table)
            if GENERATED_COMMENT_COLUMN not in columns:
                return

        if record.note_id > 0 and "id" in columns:
            sql_by_id = f"""
            UPDATE `{self._note_comment_table}`
            SET `{GENERATED_COMMENT_COLUMN}`=%s
            WHERE id=%s
            """
            cur.execute(sql_by_id, (payload, record.note_id))
            if cur.rowcount > 0:
                return

        if record.feed_id and "feed_id" in columns:
            if "id" in columns:
                sql_by_feed = f"""
                UPDATE `{self._note_comment_table}`
                SET `{GENERATED_COMMENT_COLUMN}`=%s
                WHERE feed_id=%s
                ORDER BY id DESC
                LIMIT 1
                """
            else:
                sql_by_feed = f"""
                UPDATE `{self._note_comment_table}`
                SET `{GENERATED_COMMENT_COLUMN}`=%s
                WHERE feed_id=%s
                LIMIT 1
                """
            cur.execute(sql_by_feed, (payload, record.feed_id))

    @staticmethod
    def now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
