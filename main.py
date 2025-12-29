from __future__ import annotations

import random
import time
from datetime import datetime

from modules.config_loader import COLOR_GREEN, COLOR_RED, COLOR_YELLOW, load_config, print_colored
from modules.history_store import HistoryStore, InteractionRecord
from modules.logic_processor import ACTION_QUIT, ACTION_SKIP, LogicProcessor
from modules.xhs_service import McpError, XhsService


def main() -> int:
    print("正在加载配置...")
    try:
        config = load_config()
    except Exception as exc:
        print_colored(f"[警告] 配置加载失败：{exc}", COLOR_YELLOW)
        return 1
    print_colored("配置加载完成", COLOR_GREEN)
    if not config.search.keywords:
        print_colored("[警告] 未配置关键词，程序退出", COLOR_YELLOW)
        return 1

    processed = 0
    skipped = 0
    failed = 0

    print("正在检查登录状态...")
    with XhsService() as service:
        try:
            authed = service.check_auth()
        except McpError as exc:
            print_colored(f"[错误] 登录检查失败：{exc}", COLOR_RED)
            return 1
        if not authed:
            print_colored("未登录，请先扫码登录后再运行。", COLOR_RED)
            return 1
        print_colored("已登录", COLOR_GREEN)

        print("正在连接数据库...")
        with HistoryStore() as store:
            total = store.count_all()
            print(f"数据库连接成功，历史记录 {total} 条")

            processor = LogicProcessor(service, store, config)
            should_quit = False

            round_count = 1
            while True:
                print(f"\n================ 第 {round_count} 轮开始 ================")
                processed_in_round = 0
                should_quit = False

                for keyword in config.search.keywords:
                    # Check global limit
                    if processed >= config.execution.max_count_total:
                        should_quit = True
                        break
                    
                    # Check round limit
                    if processed_in_round >= config.execution.max_comments_per_round:
                        break

                    print(f"=== 正在搜索: {keyword} ===")
                    try:
                        candidates, skipped_count = processor.search_candidates(keyword, limit=20)
                    except McpError as exc:
                        failed += 1
                        print_colored(f"[错误] 搜索失败：{exc}", COLOR_RED)
                        continue

                    print(f"搜索到 {len(candidates)} 条候选笔记...")
                    skipped += skipped_count

                    total_candidates = len(candidates)
                    for idx, candidate in enumerate(candidates, 1):
                        if processed >= config.execution.max_count_total:
                            should_quit = True
                            break
                        if processed_in_round >= config.execution.max_comments_per_round:
                            print_colored(f"已达到本轮处理上限 ({config.execution.max_comments_per_round})，停止本轮。", COLOR_YELLOW)
                            break

                        print(f"--- 笔记 [{idx}/{total_candidates}] ---")
                        print("检查历史记录...", end="")
                        if store.check_duplicate(candidate.feed_id):
                            print_colored(" [跳过]", COLOR_YELLOW)
                            skipped += 1
                            continue
                        print_colored(" [通过]", COLOR_GREEN)

                        print("检查 Token...", end="")
                        if not candidate.xsec_token:
                            print_colored(" [跳过] 无法获取 Token", COLOR_YELLOW)
                            skipped += 1
                            continue
                        print_colored(" [通过]", COLOR_GREEN)

                        print("正在获取详情...")
                        try:
                            detail = processor.fetch_detail(candidate)
                        except McpError as exc:
                            failed += 1
                            print_colored(f"[失败] 获取详情失败：{exc}", COLOR_RED)
                            print(f"等待 {config.execution.retry_interval} 秒后重试...")
                            time.sleep(config.execution.retry_interval)  # 使用配置的重试间隔
                            continue

                        title = _clean_single_line(detail.title)
                        preview = _truncate_text(_clean_single_line(detail.content), 50)
                        if not preview:
                            preview = "(无内容)"
                        print(f"标题: {title}")
                        print(f"预览: {preview}")

                        decision = processor.prompt_comment(detail)
                        if decision.action == ACTION_QUIT:
                            should_quit = True
                            break
                        if decision.action == ACTION_SKIP:
                            skipped += 1
                            continue

                        print("正在发送评论...", end="")
                        try:
                            service.post_comment(detail.feed_id, detail.xsec_token, decision.content)
                        except Exception as exc:
                            failed += 1
                            print_colored(" [失败]", COLOR_RED)
                            print_colored(f"[错误] 评论失败：{exc}", COLOR_RED)
                            continue
                        print_colored(" [成功]", COLOR_GREEN)
                        processed += 1
                        processed_in_round += 1

                        is_liked = False
                        if config.execution.auto_like:
                            like_delay = random.uniform(1, 3)
                            print(f"等待 {like_delay:.1f} 秒后点赞...")
                            time.sleep(like_delay)
                            print("正在点赞...", end="")
                            try:
                                service.like_feed(detail.feed_id, detail.xsec_token, unlike=False)
                                is_liked = True
                                print_colored(" [成功]", COLOR_GREEN)
                            except McpError as exc:
                                print_colored(" [失败]", COLOR_YELLOW)
                                print_colored(f"评论成功，但点赞失败，继续执行... ({exc})", COLOR_YELLOW)

                        record = InteractionRecord(
                            feed_id=detail.feed_id,
                            keyword=keyword,
                            comment_content=decision.content,
                            is_liked=is_liked,
                            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        )
                        print("正在写入记录...", end="")
                        store.log_action(record)
                        print_colored(" [完成]", COLOR_GREEN)

                        interval_start, interval_end = config.execution.interval_range
                        wait_time = random.uniform(interval_start, interval_end)
                        print(f"等待 {wait_time:.1f} 秒...")
                        time.sleep(wait_time)
                    
                    # If we broke out due to round limit
                    if processed_in_round >= config.execution.max_comments_per_round:
                        break

                if should_quit or processed >= config.execution.max_count_total:
                    break
                
                print(f"\n本轮结束，已处理 {processed_in_round} 条。休息 {config.execution.round_interval} 秒...")
                time.sleep(config.execution.round_interval)
                round_count += 1

            print("================ 运行结束 ================")
            print(f"✅ 成功评论: {processed}")
            print(f"⏭️  跳过/重复: {skipped}")
            print(f"❌ 失败错误: {failed}")
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
