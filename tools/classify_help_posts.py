from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pymysql
import requests


@dataclass
class JudgeResult:
    is_help_post: int
    reason: str


class AIHelpPostClassifier:
    """Use an OpenAI-compatible API to classify whether a post is a help-seeking post."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def classify(self, title: str, content: str) -> JudgeResult:
        prompt = (
            "你是内容审核助手。请判断以下小红书笔记是否是“求助帖”。\n"
            "求助帖特征：作者明确提问、征求建议、请求解决方案、求推荐、求经验等。\n"
            "如果是经验分享/展示/广告，不算求助帖。\n\n"
            f"标题：{title or '(空)'}\n"
            f"正文：{content or '(空)'}\n\n"
            "只返回 JSON，不要额外文字，格式如下：\n"
            '{"is_help_post": 0 或 1, "reason": "一句简短中文理由"}'
        )

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是严谨的中文内容分类器。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()

        parsed = _safe_parse_json(text)
        if not parsed:
            raise ValueError(f"模型输出无法解析为 JSON: {text}")

        value = int(parsed.get("is_help_post", 0))
        reason = str(parsed.get("reason", "")).strip() or "模型未提供理由"
        return JudgeResult(is_help_post=1 if value == 1 else 0, reason=reason)


def _safe_parse_json(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    if not text:
        return None

    # raw JSON
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    # fenced JSON
    if "```" in text:
        chunks = text.split("```")
        for chunk in chunks:
            chunk = chunk.strip()
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            try:
                obj = json.loads(chunk)
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                continue
    return None


def ensure_columns(conn: pymysql.Connection, table: str) -> None:
    alter_sql = f"""
    ALTER TABLE `{table}`
      ADD COLUMN IF NOT EXISTS `is_help_post` TINYINT NULL COMMENT 'AI判断:是否求助帖(1是0否)',
      ADD COLUMN IF NOT EXISTS `help_post_reason` VARCHAR(255) NULL COMMENT 'AI判断理由',
      ADD COLUMN IF NOT EXISTS `help_post_scored_at` DATETIME NULL COMMENT 'AI判断时间';
    """
    with conn.cursor() as cur:
        cur.execute(alter_sql)
    conn.commit()


def fetch_pending_rows(conn: pymysql.Connection, table: str, batch_size: int) -> List[Tuple[Any, ...]]:
    sql = f"""
    SELECT id, title, `desc`
    FROM `{table}`
    WHERE is_help_post IS NULL
    ORDER BY id ASC
    LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (batch_size,))
        return list(cur.fetchall())


def update_row(conn: pymysql.Connection, table: str, row_id: int, result: JudgeResult) -> None:
    sql = f"""
    UPDATE `{table}`
    SET is_help_post=%s,
        help_post_reason=%s,
        help_post_scored_at=%s
    WHERE id=%s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (result.is_help_post, result.reason[:255], datetime.utcnow(), row_id))
    conn.commit()


def get_db_conn() -> pymysql.Connection:
    host = os.getenv("MYSQL_DB_HOST", "127.0.0.1")
    port = int(os.getenv("MYSQL_DB_PORT", "3306"))
    user = os.getenv("MYSQL_DB_USER", "root")
    password = os.getenv("MYSQL_DB_PWD", "")
    db = os.getenv("MYSQL_DB_NAME", "media_crawler")

    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=db,
        charset="utf8mb4",
        autocommit=False,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用 AI 判断数据库笔记是否为求助帖")
    parser.add_argument("--table", default="xhs_note", help="目标表名，默认 xhs_note")
    parser.add_argument("--batch-size", type=int, default=50, help="单批处理数量，默认 50")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 OPENAI_API_KEY，无法进行 AI 判断")

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    classifier = AIHelpPostClassifier(base_url=base_url, api_key=api_key, model=model)

    conn = get_db_conn()
    try:
        ensure_columns(conn, args.table)
        rows = fetch_pending_rows(conn, args.table, args.batch_size)
        if not rows:
            print("没有待处理数据（is_help_post 全部已判定）")
            return 0

        done = 0
        for row_id, title, desc in rows:
            result = classifier.classify(title or "", desc or "")
            update_row(conn, args.table, int(row_id), result)
            done += 1
            print(f"[{done}/{len(rows)}] id={row_id} -> is_help_post={result.is_help_post} ({result.reason})")

        print(f"完成：共处理 {done} 条")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
