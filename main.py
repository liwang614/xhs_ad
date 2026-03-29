from __future__ import annotations

import random
import time

from modules.config_loader import COLOR_GREEN, COLOR_YELLOW, load_config, print_colored
from modules.database_store import DatabaseStore, InteractionRecord
from modules.help_post_judge import AIHelpPostJudge, HelpPostJudgeError
from modules.logic_processor import ACTION_QUIT, ACTION_SKIP, LogicProcessor
from tools.classify_help_posts import run_batch_classify_help_posts
from tools.generate_and_reply_help_comments import run_generate_and_reply_help_comments
from tools.analyze_business_opportunities import run_batch_analysis


def main() -> int:
    print("正在加载配置...")
    try:
        config = load_config()
    except Exception as exc:
        print_colored(f"[警告] 配置加载失败：{exc}", COLOR_YELLOW)
        return 1
    print_colored("配置加载完成", COLOR_GREEN)
    if not config.search.keywords and config.ai_judge.generate_reply_mode == "manual":
        print_colored("[警告] 未配置关键词，程序退出", COLOR_YELLOW)
        return 1

    processed = 0
    skipped = 0
    failed = 0
    help_judged = 0
    help_judge_failed = 0
    generated_success = 0
    generated_failed = 0
    replied_success = 0
    replied_failed = 0

    judge: AIHelpPostJudge | None = None
    if config.ai_judge.mode != "manual":
        try:
            judge = AIHelpPostJudge(
                provider=config.ai_judge.provider,
                model=config.ai_judge.judge_model,
                base_url=config.ai_judge.base_url,
                timeout=config.ai_judge.timeout,
                note_prompt_template=config.ai_judge.note_prompt_template,
                comment_prompt_template=config.ai_judge.comment_prompt_template,
            )
            print(
                "AI判定已启用："
                f"mode={config.ai_judge.mode}, provider={config.ai_judge.provider}, model={config.ai_judge.judge_model}"
            )
        except HelpPostJudgeError as exc:
            print_colored(f"[警告] AI判定初始化失败，已降级为不判定：{exc}", COLOR_YELLOW)
            judge = None

    print("正在连接数据库...")
    with DatabaseStore() as store:
        total = store.count_all_interactions()
        print(f"数据库连接成功，历史记录 {total} 条")

        # --- 新默认流程：商业机会分析 ---
        if config.analysis.enabled:
            print("\n=== 商业机会分析模式 ===")
            from modules.analysis_pipeline import AnalysisPipeline
            from modules.analysis_registry import AnalysisRegistry
            from modules.providers.codexexec_provider import CodexExecError, CodexExecProvider

            registry = AnalysisRegistry()
            try:
                provider = CodexExecProvider(
                    command=config.analysis.command,
                    timeout=config.analysis.timeout,
                )
                registry.register(provider)
            except CodexExecError as exc:
                print_colored(f"[警告] codexexec 不可用，跳过分析: {exc}", COLOR_YELLOW)
                registry = None

            if registry and registry.get_default():
                pipeline = AnalysisPipeline(registry.get_default())
                stats = run_batch_analysis(
                    store=store,
                    pipeline=pipeline,
                    table_names=config.analysis.tables,
                    batch_size=config.analysis.batch_size,
                    only_unanalyzed=True,
                    verbose=True,
                )
                print(f"分析完成: 总计={stats.total}, 需求={stats.help_post}, "
                      f"solution_request={stats.solution_request}, 失败={stats.failed}")
                print("请通过 GUI 查看结果: python tools/run_gui.py")

            print("=== 分析模式结束 ===\n")

        # --- 旧流程（默认不触发） ---
        processor = LogicProcessor(config)
        should_quit = False
        round_count = 1

        while True:
            print(f"\n================ 第 {round_count} 轮开始 ================")
            processed_in_round = 0

            if judge and config.ai_judge.mode == "batch":
                judged_count, failed_count = run_batch_classify_help_posts(
                    store=store,
                    judge=judge,
                    table_names=config.ai_judge.tables,
                    batch_size=config.ai_judge.batch_size,
                    verbose=True,
                )
                help_judged += judged_count
                help_judge_failed += failed_count
                if judged_count > 0 or failed_count > 0:
                    print(f"AI批量判定总计：成功 {judged_count} 条，失败 {failed_count} 条")

            if config.ai_judge.generate_reply_mode in ("generate", "reply", "all"):
                try:
                    stats = run_generate_and_reply_help_comments(
                        store=store,
                        config=config,
                        mode=config.ai_judge.generate_reply_mode,
                        batch_size=config.ai_judge.batch_size,
                        table_names=config.ai_judge.tables,
                        reply_target_ids=config.ai_judge.reply_target_ids,
                        overwrite_generated_comment=config.ai_judge.overwrite_generated_comment,
                        verbose=True,
                    )
                    generated_success += stats.generate_success
                    generated_failed += stats.generate_failed
                    replied_success += stats.reply_success
                    replied_failed += stats.reply_failed
                except Exception as exc:
                    failed += 1
                    print_colored(f"[失败] 生成/回复流程异常：{exc}", COLOR_YELLOW)

            for keyword in config.search.keywords:
                if processed >= config.execution.max_count_total:
                    should_quit = True
                    break
                if processed_in_round >= config.execution.max_comments_per_round:
                    break

                print(f"=== 数据库检索关键词: {keyword} ===")
                notes = store.search_notes(keyword, limit=20)
                candidates = processor.filter_candidates(notes)
                print(f"检索到 {len(candidates)} 条候选记录...")

                total_candidates = len(candidates)
                for idx, note in enumerate(candidates, 1):
                    if processed >= config.execution.max_count_total:
                        should_quit = True
                        break
                    if processed_in_round >= config.execution.max_comments_per_round:
                        print_colored(
                            f"已达到本轮处理上限 ({config.execution.max_comments_per_round})，停止本轮。",
                            COLOR_YELLOW,
                        )
                        break

                    print(f"--- 记录 [{idx}/{total_candidates}] ---")

                    try:
                        is_duplicate = store.is_duplicate_feed(note.feed_id)
                        store.mark_note_duplicate(note.id, is_duplicate)
                    except Exception as exc:
                        failed += 1
                        print_colored(f"[失败] 重复检测失败：{exc}", COLOR_YELLOW)
                        continue

                    if is_duplicate:
                        print_colored("[跳过] 数据库标记重复记录", COLOR_YELLOW)
                        skipped += 1
                        continue

                    if store.check_duplicate_processed(note.feed_id):
                        print_colored("[跳过] 历史已处理", COLOR_YELLOW)
                        skipped += 1
                        continue

                    current_is_help_post = note.is_help_post
                    if judge and config.ai_judge.mode in ("auto", "immediate") and current_is_help_post is None:
                        judged = judge.classify_row(note.id, note.title, note.content)
                        if judged is None:
                            help_judge_failed += 1
                        else:
                            try:
                                store.update_help_post(note.id, judged)
                                help_judged += 1
                                current_is_help_post = judged
                            except Exception as exc:
                                help_judge_failed += 1
                                judge.log_error(note.id, f"db update failed: {exc}")
                    if current_is_help_post != 1:
                        print_colored("[跳过] is_help_post != 1", COLOR_YELLOW)
                        skipped += 1
                        continue

                    title = _clean_single_line(note.title)
                    preview = _truncate_text(_clean_single_line(note.content), 50)
                    if not preview:
                        preview = "(无内容)"
                    print(f"标题: {title}")
                    print(f"预览: {preview}")

                    decision = processor.prompt_comment(note)
                    if decision.action == ACTION_QUIT:
                        should_quit = True
                        break
                    if decision.action == ACTION_SKIP:
                        skipped += 1
                        continue

                    record = InteractionRecord(
                        note_id=note.id,
                        feed_id=note.feed_id,
                        keyword=keyword,
                        comment_content=decision.content,
                        is_liked=False,
                        is_duplicate=0,
                        created_at=store.now_text(),
                    )

                    print("正在写入记录...", end="")
                    try:
                        store.log_action(record)
                    except Exception as exc:
                        failed += 1
                        print_colored(" [失败]", COLOR_YELLOW)
                        print_colored(f"[错误] 写入失败：{exc}", COLOR_YELLOW)
                        continue

                    print_colored(" [完成]", COLOR_GREEN)
                    processed += 1
                    processed_in_round += 1

                    interval_start, interval_end = config.execution.interval_range
                    wait_time = random.uniform(interval_start, interval_end)
                    print(f"等待 {wait_time:.1f} 秒...")
                    time.sleep(wait_time)

                if processed_in_round >= config.execution.max_comments_per_round:
                    break

            if should_quit or processed >= config.execution.max_count_total:
                break

            print(f"\n本轮结束，已处理 {processed_in_round} 条。休息 {config.execution.round_interval} 秒...")
            time.sleep(config.execution.round_interval)
            round_count += 1

        print("================ 运行结束 ================")
        print(f"成功记录: {processed}")
        print(f"跳过/重复: {skipped}")
        print(f"失败错误: {failed}")
        print(f"AI判定写入: {help_judged}")
        print(f"AI判定失败: {help_judge_failed}")
        print(f"文案生成成功: {generated_success}")
        print(f"文案生成失败: {generated_failed}")
        print(f"自动回复成功: {replied_success}")
        print(f"自动回复失败: {replied_failed}")
        print("==========================================")

    return 0


def _clean_single_line(text: str) -> str:
    if not text:
        return ""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " / ").strip()


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit]


if __name__ == "__main__":
    raise SystemExit(main())
