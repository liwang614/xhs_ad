from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.config_loader import AppConfig, load_config
from modules.database_store import (
    DatabaseStore,
    HelpCommentGenerateRecord,
    HelpCommentReplyRecord,
)
from modules.help_post_judge import AIHelpPostJudge, HelpPostJudgeError
from modules.xhs_service import McpError, XhsService

DEFAULT_LOG_PATH = "logs/generate_reply_errors.log"


@dataclass
class GenerateReplyStats:
    generate_success: int = 0
    generate_failed: int = 0
    reply_success: int = 0
    reply_failed: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成并回复 is_help_post=1 的评论")
    parser.add_argument("--config", default="config.json", help="配置文件路径，默认 config.json")
    parser.add_argument(
        "--mode",
        choices=["generate", "reply", "all"],
        default=None,
        help="执行模式，不传则读取 ai_judge.generate_reply_mode",
    )
    parser.add_argument("--batch-size", type=int, default=None, help="每表处理数量上限")
    parser.add_argument("--tables", default=None, help="覆盖配置中的表列表，逗号分隔")
    parser.add_argument("--reply-ids", default=None, help="仅回复指定行id，逗号分隔，如 1,2,3")
    parser.add_argument(
        "--overwrite-generated",
        action="store_true",
        help="生成时覆盖已有 generated_comment_content",
    )
    parser.add_argument("--log-path", default=DEFAULT_LOG_PATH, help="错误日志文件路径")
    return parser.parse_args()


def run_generate_and_reply_help_comments(
    *,
    store: DatabaseStore,
    config: AppConfig,
    mode: str,
    batch_size: int,
    table_names: Sequence[str],
    reply_target_ids: Optional[Sequence[int]] = None,
    overwrite_generated_comment: Optional[bool] = None,
    verbose: bool = True,
    log_path: str = DEFAULT_LOG_PATH,
) -> GenerateReplyStats:
    stats = GenerateReplyStats()
    normalized_mode = (mode or "").strip().lower()
    if normalized_mode not in ("generate", "reply", "all"):
        raise ValueError(f"unsupported mode: {mode}")

    overwrite = (
        config.ai_judge.overwrite_generated_comment
        if overwrite_generated_comment is None
        else bool(overwrite_generated_comment)
    )
    normalized_reply_ids = _normalize_id_list(reply_target_ids)
    generate_row_ids: Optional[Sequence[int]] = None
    if normalized_mode == "all" and normalized_reply_ids:
        generate_row_ids = normalized_reply_ids

    generated_row_ids_by_table: Dict[str, List[int]] = {}
    if normalized_mode in ("generate", "all"):
        generated_row_ids_by_table = _run_generate_mode(
            store=store,
            config=config,
            table_names=table_names,
            batch_size=batch_size,
            overwrite_generated_comment=overwrite,
            explicit_row_ids=generate_row_ids,
            stats=stats,
            verbose=verbose,
            log_path=log_path,
        )

    if normalized_mode in ("reply", "all"):
        if normalized_mode == "reply" and not normalized_reply_ids:
            if verbose:
                print("reply 模式未配置 reply_target_ids，已跳过")
            return stats

        strict_id_filter = False
        if normalized_mode == "all" and not normalized_reply_ids:
            reply_ids_by_table = generated_row_ids_by_table
            strict_id_filter = True
        elif normalized_reply_ids:
            reply_ids_by_table = {table_name: normalized_reply_ids for table_name in table_names}
            strict_id_filter = True
        else:
            reply_ids_by_table = {}

        _run_reply_mode(
            store=store,
            config=config,
            table_names=table_names,
            batch_size=batch_size,
            reply_ids_by_table=reply_ids_by_table,
            strict_id_filter=strict_id_filter,
            stats=stats,
            verbose=verbose,
            log_path=log_path,
        )

    return stats


def _run_generate_mode(
    *,
    store: DatabaseStore,
    config: AppConfig,
    table_names: Sequence[str],
    batch_size: int,
    overwrite_generated_comment: bool,
    explicit_row_ids: Optional[Sequence[int]],
    stats: GenerateReplyStats,
    verbose: bool,
    log_path: str,
) -> Dict[str, List[int]]:
    generator: Optional[AIHelpPostJudge] = None
    generated_row_ids_by_table: Dict[str, List[int]] = {}

    for table_name in table_names:
        try:
            rows = store.fetch_help_comments_for_generation(
                batch_size,
                table_name=table_name,
                overwrite_existing=overwrite_generated_comment,
                row_ids=explicit_row_ids,
            )
        except Exception as exc:
            stats.generate_failed += 1
            _log_error(log_path, stage="generate", table_name=table_name, row_id=0, error=str(exc))
            if verbose:
                print(f"[{table_name}] 读取待生成数据失败: {exc}")
            continue

        if not rows:
            if verbose:
                print(f"[{table_name}] 没有待生成数据")
            continue

        generated_row_ids: List[int] = []
        for row in rows:
            if generator is None:
                try:
                    generator = AIHelpPostJudge(
                        provider=config.ai_judge.provider,
                        model=config.ai_judge.generate_model,
                        base_url=config.ai_judge.base_url,
                        timeout=config.ai_judge.timeout,
                        note_prompt_template=config.ai_judge.note_prompt_template,
                        comment_prompt_template=config.ai_judge.comment_prompt_template,
                    )
                except HelpPostJudgeError as exc:
                    raise RuntimeError(f"文案生成模型初始化失败: {exc}") from exc

            prompt = _render_generate_prompt(config.ai_judge.generate_prompt_template, row)
            try:
                generated = generator.generate_text(prompt)
            except Exception as exc:
                stats.generate_failed += 1
                _log_error(
                    log_path,
                    stage="generate",
                    table_name=table_name,
                    row_id=row.row_id,
                    error=f"llm generate failed: {exc}",
                )
                if verbose:
                    print(f"[{table_name}] id={row.row_id} 生成失败: {exc}")
                continue

            try:
                store.update_generated_comment(
                    row_id=row.row_id,
                    generated_comment_content=generated,
                    table_name=table_name,
                )
            except Exception as exc:
                stats.generate_failed += 1
                _log_error(
                    log_path,
                    stage="generate",
                    table_name=table_name,
                    row_id=row.row_id,
                    error=f"db update failed: {exc}",
                )
                if verbose:
                    print(f"[{table_name}] id={row.row_id} 写库失败: {exc}")
                continue

            stats.generate_success += 1
            generated_row_ids.append(row.row_id)
            if verbose:
                print(f"[{table_name}] id={row.row_id} -> generated_comment_content 已写入")

        if generated_row_ids:
            generated_row_ids_by_table[table_name] = generated_row_ids

    return generated_row_ids_by_table


def _run_reply_mode(
    *,
    store: DatabaseStore,
    config: AppConfig,
    table_names: Sequence[str],
    batch_size: int,
    reply_ids_by_table: Dict[str, Sequence[int]],
    strict_id_filter: bool,
    stats: GenerateReplyStats,
    verbose: bool,
    log_path: str,
) -> None:
    try:
        mcp = XhsService(url=config.mcp.url, timeout=float(config.ai_judge.timeout))
    except Exception as exc:
        raise RuntimeError(f"MCP 客户端初始化失败: {exc}") from exc

    try:
        for table_name in table_names:
            if strict_id_filter and table_name not in reply_ids_by_table:
                if verbose:
                    print(f"[{table_name}] 未命中回复ID范围，已跳过")
                continue
            row_ids = reply_ids_by_table.get(table_name)
            try:
                rows = store.fetch_help_comments_for_reply(
                    batch_size,
                    table_name=table_name,
                    row_ids=row_ids,
                )
            except Exception as exc:
                stats.reply_failed += 1
                _log_error(log_path, stage="reply", table_name=table_name, row_id=0, error=str(exc))
                if verbose:
                    print(f"[{table_name}] 读取待回复数据失败: {exc}")
                continue

            if not rows:
                if verbose:
                    print(f"[{table_name}] 没有待回复数据")
                continue

            for row in rows:
                missing = _missing_reply_fields(row)
                if missing:
                    reason = f"missing required fields: {','.join(missing)}"
                    stats.reply_failed += 1
                    _log_error(log_path, stage="reply", table_name=table_name, row_id=row.row_id, error=reason)
                    if verbose:
                        print(f"[{table_name}] id={row.row_id} 跳过: {reason}")
                    continue

                try:
                    mcp.reply_comment_in_feed(
                        comment_id=row.comment_id,
                        feed_id=row.feed_id,
                        xsec_token=row.xsec_token,
                        content=row.content,
                        tool_name=config.mcp.reply_tool_name,
                    )
                except Exception as exc:
                    message = str(exc)
                    if isinstance(exc, McpError):
                        message = f"mcp call failed: {message}"
                    stats.reply_failed += 1
                    _log_error(
                        log_path,
                        stage="reply",
                        table_name=table_name,
                        row_id=row.row_id,
                        error=message,
                    )
                    if verbose:
                        print(f"[{table_name}] id={row.row_id} 回复失败: {message}")
                    continue

                stats.reply_success += 1
                if verbose:
                    print(f"[{table_name}] id={row.row_id} -> reply_comment_in_feed 已调用")
    finally:
        mcp.close()


def _render_generate_prompt(template: str, row: HelpCommentGenerateRecord) -> str:
    mapping = {
        "table_name": row.table_name,
        "row_id": str(row.row_id),
        "comment_id": row.comment_id,
        "feed_id": row.feed_id,
        "xsec_token": row.xsec_token,
        "title": row.title,
        "content": row.content,
        "generated_comment_content": row.generated_comment_content,
    }
    out = template
    for key, value in mapping.items():
        out = out.replace(f"{{{{{key}}}}}", value or "")
    return out


def _missing_reply_fields(row: HelpCommentReplyRecord) -> List[str]:
    missing: List[str] = []
    if not row.comment_id:
        missing.append("comment_id")
    if not row.feed_id:
        missing.append("feed_id")
    if not row.xsec_token:
        missing.append("xsec_token")
    if not row.content:
        missing.append("content")
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


def _parse_table_csv(text: Optional[str]) -> List[str]:
    if not text:
        return []
    out: List[str] = []
    for chunk in text.split(","):
        table = chunk.strip()
        if not table:
            continue
        if table not in out:
            out.append(table)
    return out


def _log_error(log_path: str, *, stage: str, table_name: str, row_id: int, error: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{ts}\tstage={stage}\ttable={table_name}\trow_id={row_id}\terror={error}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def main() -> int:
    args = parse_args()
    config = load_config(args.config)

    mode = (args.mode or config.ai_judge.generate_reply_mode).strip().lower()
    if mode == "manual":
        print("generate_reply_mode=manual，不执行生成/回复")
        return 0
    if mode not in ("generate", "reply", "all"):
        raise RuntimeError(f"不支持的 mode: {mode}")

    batch_size = args.batch_size or config.ai_judge.batch_size
    tables = _parse_table_csv(args.tables) or config.ai_judge.tables
    if not tables:
        raise RuntimeError("未配置 ai_judge.tables，无法执行")

    reply_target_ids = _parse_id_csv(args.reply_ids) if args.reply_ids is not None else config.ai_judge.reply_target_ids
    overwrite_generated = args.overwrite_generated or config.ai_judge.overwrite_generated_comment

    with DatabaseStore() as store:
        stats = run_generate_and_reply_help_comments(
            store=store,
            config=config,
            mode=mode,
            batch_size=batch_size,
            table_names=tables,
            reply_target_ids=reply_target_ids,
            overwrite_generated_comment=overwrite_generated,
            verbose=True,
            log_path=args.log_path,
        )

    print(
        "完成: "
        f"generate_success={stats.generate_success}, generate_failed={stats.generate_failed}, "
        f"reply_success={stats.reply_success}, reply_failed={stats.reply_failed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
