from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.config_loader import load_config
from modules.database_store import DatabaseStore, PendingLikeRecord
from modules.xhs_service import McpError, XhsService

DEFAULT_BATCH_SIZE = 20
DEFAULT_LOG_PATH = "logs/like_commented_posts_errors.log"
DEFAULT_LIKE_TOOL_NAME = "like_feed"


@dataclass
class LikeStats:
    success: int = 0
    failed: int = 0
    skipped: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="给 interactions 中已评论但未点赞的帖子执行点赞")
    parser.add_argument("--config", default="config.json", help="配置文件路径，默认 config.json")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="本次处理数量上限")
    parser.add_argument("--row-ids", default=None, help="仅处理指定 interactions.id，逗号分隔，如 1,2,3")
    parser.add_argument("--log-path", default=DEFAULT_LOG_PATH, help="错误日志文件路径")
    return parser.parse_args()


def run_like_commented_posts(
    *,
    store: DatabaseStore,
    mcp: XhsService,
    batch_size: int,
    row_ids: Optional[Sequence[int]] = None,
    verbose: bool = True,
    log_path: str = DEFAULT_LOG_PATH,
    history_table_name: str = "interactions",
) -> LikeStats:
    stats = LikeStats()
    rows = store.fetch_pending_likes(batch_size, row_ids=row_ids)
    if not rows:
        if verbose:
            print("没有待点赞记录")
        return stats

    for row in rows:
        missing = _missing_like_fields(row)
        if missing:
            stats.skipped += 1
            reason = f"missing required fields: {','.join(missing)}"
            _log_error(log_path, table_name=history_table_name, row_id=row.interaction_id, error=reason)
            if verbose:
                print(f"[{history_table_name}] id={row.interaction_id} 跳过: {reason}")
            continue

        try:
            mcp.like_feed(
                feed_id=row.feed_id,
                xsec_token=row.xsec_token,
                tool_name=DEFAULT_LIKE_TOOL_NAME,
            )
        except Exception as exc:
            message = str(exc)
            if isinstance(exc, McpError):
                message = f"mcp call failed: {message}"
            stats.failed += 1
            _log_error(log_path, table_name=history_table_name, row_id=row.interaction_id, error=message)
            if verbose:
                print(f"[{history_table_name}] id={row.interaction_id} 点赞失败: {message}")
            continue

        try:
            store.mark_feed_liked(row.feed_id, is_liked=True)
        except Exception as exc:
            stats.failed += 1
            message = f"db update failed after like success: {exc}"
            _log_error(log_path, table_name=history_table_name, row_id=row.interaction_id, error=message)
            if verbose:
                print(f"[{history_table_name}] id={row.interaction_id} 回写 is_liked 失败: {exc}")
            continue

        stats.success += 1
        if verbose:
            print(f"[{history_table_name}] id={row.interaction_id} -> like_feed 已调用")

    return stats


def _missing_like_fields(row: PendingLikeRecord) -> List[str]:
    missing: List[str] = []
    if not row.feed_id:
        missing.append("feed_id")
    if not row.xsec_token:
        missing.append("xsec_token")
    return missing


def _normalize_id_list(values: Optional[Sequence[int]]) -> List[int]:
    if not values:
        return []
    out: List[int] = []
    for item in values:
        try:
            row_id = int(item)
        except (TypeError, ValueError):
            continue
        if row_id <= 0:
            continue
        if row_id not in out:
            out.append(row_id)
    return out


def _parse_id_csv(text: Optional[str]) -> List[int]:
    if not text:
        return []
    chunks = [chunk.strip() for chunk in text.split(",")]
    return _normalize_id_list(chunks)


def _log_error(log_path: str, *, table_name: str, row_id: int, error: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{ts}\ttable={table_name}\trow_id={row_id}\terror={error}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    row_ids = _parse_id_csv(args.row_ids)
    history_table_name = (os.getenv("MYSQL_HISTORY_TABLE", "interactions") or "interactions").strip()

    with DatabaseStore() as store, XhsService(url=config.mcp.url, timeout=float(config.ai_judge.timeout)) as mcp:
        stats = run_like_commented_posts(
            store=store,
            mcp=mcp,
            batch_size=args.batch_size,
            row_ids=row_ids,
            verbose=True,
            log_path=args.log_path,
            history_table_name=history_table_name,
        )

    print(f"完成: success={stats.success}, failed={stats.failed}, skipped={stats.skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
