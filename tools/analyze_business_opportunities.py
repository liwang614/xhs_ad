from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.analysis_pipeline import AnalysisPipeline
from modules.analysis_registry import AnalysisRegistry
from modules.config_loader import load_config
from modules.database_store import DatabaseStore
from modules.providers.codexexec_provider import CodexExecError, CodexExecProvider


@dataclass
class BatchStats:
    total: int = 0
    help_post: int = 0
    solution_request: int = 0
    failed: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量分析商业机会（求解决方案）")
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    parser.add_argument("--batch-size", type=int, default=None, help="本次处理数量上限")
    parser.add_argument("--tables", default=None, help="目标表列表，逗号分隔")
    parser.add_argument("--all", action="store_true", help="分析全部记录（含已分析）")
    return parser.parse_args()


def run_batch_analysis(
    *,
    store: DatabaseStore,
    pipeline: AnalysisPipeline,
    table_names: list[str],
    batch_size: int,
    only_unanalyzed: bool = True,
    verbose: bool = True,
) -> BatchStats:
    stats = BatchStats()

    for table_name in table_names:
        rows = store.fetch_pending_analysis(
            batch_size,
            table_name=table_name,
            only_unanalyzed=only_unanalyzed,
        )
        if not rows:
            if verbose:
                print(f"[{table_name}] 没有待分析数据")
            continue

        if verbose:
            print(f"[{table_name}] 读取到 {len(rows)} 条待分析记录")

        for record in rows:
            stats.total += 1
            pipe_result = pipeline.analyze_one(record)

            if not pipe_result.success:
                stats.failed += 1
                store.mark_analysis_failed(pipe_result.row_id, table_name=table_name)
                if verbose:
                    print(f"  id={pipe_result.row_id} FAILED: {pipe_result.error}")
                continue

            result = pipe_result.result
            store.write_analysis_result(pipe_result.row_id, result, table_name=table_name)

            if result.is_help_post == 1:
                stats.help_post += 1
            if result.opportunity_type == "solution_request":
                stats.solution_request += 1

            if verbose:
                label = result.opportunity_type
                score = result.lead_score
                print(f"  id={pipe_result.row_id} -> {label} (score={score})")

    return stats


def main() -> int:
    args = parse_args()
    config = load_config(args.config)

    if not config.analysis.enabled:
        print("analysis.enabled=false，已跳过")
        return 0

    registry = AnalysisRegistry()
    try:
        provider = CodexExecProvider(
            command=config.analysis.command,
            timeout=config.analysis.timeout,
        )
        registry.register(provider)
    except CodexExecError as exc:
        print(f"codexexec provider 初始化失败: {exc}")
        return 1

    active = registry.get_default()
    if active is None:
        print("没有可用的 analysis provider")
        return 1

    pipeline = AnalysisPipeline(active)
    batch_size = args.batch_size or config.analysis.batch_size
    tables = [t.strip() for t in args.tables.split(",")] if args.tables else config.analysis.tables

    with DatabaseStore() as store:
        stats = run_batch_analysis(
            store=store,
            pipeline=pipeline,
            table_names=tables,
            batch_size=batch_size,
            only_unanalyzed=not args.all,
            verbose=True,
        )

    print("=" * 40)
    print(f"总处理数:            {stats.total}")
    print(f"判定为需求(1):       {stats.help_post}")
    print(f"solution_request:    {stats.solution_request}")
    print(f"失败数量:            {stats.failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
