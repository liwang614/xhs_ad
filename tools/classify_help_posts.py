from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.config_loader import load_config
from modules.database_store import DatabaseStore
from modules.help_post_judge import AIHelpPostJudge, HelpPostJudgeError


def run_batch_classify_help_posts(
    *,
    store: DatabaseStore,
    judge: AIHelpPostJudge,
    table_names: Iterable[str],
    batch_size: int,
    verbose: bool = True,
) -> Tuple[int, int]:
    total_success = 0
    total_failed = 0

    for table_name in table_names:
        success = 0
        failed = 0
        rows = store.fetch_pending_help_posts(batch_size, table_name=table_name)
        if not rows:
            if verbose:
                print(f"[{table_name}] 没有待处理数据（is_help_post 全部已判定）")
            continue

        for row_id, title, desc in rows:
            judged = judge.classify_row(row_id=row_id, title=title, desc=desc)
            if judged is None:
                failed += 1
                if verbose:
                    print(f"[{table_name}] id={row_id} -> 失败，保持 is_help_post=NULL")
                continue

            try:
                store.update_help_post(row_id=row_id, is_help_post=judged, table_name=table_name)
            except Exception as exc:
                failed += 1
                judge.log_error(row_id=row_id, error=f"db update failed on {table_name}: {exc}")
                if verbose:
                    print(f"[{table_name}] id={row_id} -> 数据库更新失败，保持 is_help_post=NULL")
                continue

            success += 1
            if verbose:
                print(f"[{table_name}] id={row_id} -> is_help_post={judged}")

        total_success += success
        total_failed += failed
        if verbose:
            print(f"[{table_name}] 完成: success={success}, failed={failed}")

    return total_success, total_failed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="手动触发 AI 判断求助帖并写入 is_help_post")
    parser.add_argument("--config", default="config.json", help="配置文件路径，默认 config.json")
    parser.add_argument("--batch-size", type=int, default=None, help="本次处理数量上限")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)

    try:
        judge = AIHelpPostJudge(
            provider=config.ai_judge.provider,
            model=config.ai_judge.judge_model,
            base_url=config.ai_judge.base_url,
            timeout=config.ai_judge.timeout,
            note_prompt_template=config.ai_judge.note_prompt_template,
            comment_prompt_template=config.ai_judge.comment_prompt_template,
        )
    except HelpPostJudgeError as exc:
        raise RuntimeError(f"AI判定初始化失败: {exc}") from exc

    batch_size = args.batch_size or config.ai_judge.batch_size

    with DatabaseStore() as store:
        total_success, total_failed = run_batch_classify_help_posts(
            store=store,
            judge=judge,
            table_names=config.ai_judge.tables,
            batch_size=batch_size,
            verbose=True,
        )

    print(f"总计完成: success={total_success}, failed={total_failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
