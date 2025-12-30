from __future__ import annotations

from dataclasses import dataclass
import json
import random
from typing import Any, Dict, List, Tuple

from .config_loader import (
    COLOR_GREEN,
    COLOR_YELLOW,
    AppConfig,
    build_search_filters,
    print_colored,
)
from .history_store import HistoryStore
from .xhs_service import XhsService

EXCLUDE_KEYWORDS = ["广告", "商单", "推广"]

ACTION_SEND = "send"
ACTION_SKIP = "skip"
ACTION_QUIT = "quit"


@dataclass(frozen=True)
class FeedCandidate:
    feed_id: str
    xsec_token: str
    title: str
    display_title: str
    raw: Dict[str, Any]


@dataclass(frozen=True)
class FeedDetail:
    feed_id: str
    xsec_token: str
    title: str
    content: str
    raw: Dict[str, Any]


@dataclass(frozen=True)
class CommentDecision:
    action: str
    content: str = ""


class LogicProcessor:
    def __init__(self, service: XhsService, store: HistoryStore, config: AppConfig) -> None:
        self.service = service
        self.store = store
        self.config = config

    def search_candidates(self, keyword: str, limit: int = 10) -> Tuple[List[FeedCandidate], int]:
        filters = build_search_filters(self.config.search)
        result = self.service.search_feeds(keyword, filters=filters)
        payload = _unwrap_content_payload(result)
        items = _extract_items(payload)

        candidates: List[FeedCandidate] = []
        skipped = 0

        for index, item in enumerate(items):
            if index >= limit:
                break
            if not _is_note_item(item):
                skipped += 1
                continue
            feed_id = _normalize_id(item.get("id") or item.get("feed_id") or item.get("note_id"))
            if not feed_id:
                skipped += 1
                continue

            note_card = _get_note_card(item)
            display_title = _pick_first_str(
                note_card.get("display_title"),
                note_card.get("displayTitle"),
                note_card.get("title"),
            )
            title = _pick_first_str(display_title, note_card.get("desc"))
            if _is_excluded_title(title):
                skipped += 1
                continue

            xsec_token = _pick_first_str(
                item.get("xsec_token"),
                item.get("xsecToken"),
                note_card.get("xsec_token"),
                note_card.get("xsecToken"),
            )

            candidates.append(
                FeedCandidate(
                    feed_id=feed_id,
                    xsec_token=xsec_token,
                    title=title or display_title or "无标题",
                    display_title=display_title or title or "无标题",
                    raw=item,
                )
            )

        return candidates, skipped

    def fetch_detail(self, candidate: FeedCandidate) -> FeedDetail:
        raw_detail = self.service.get_feed_detail(
            candidate.feed_id,
            candidate.xsec_token,
            load_all_comments=False,
        )
        detail = _unwrap_content_payload(raw_detail)
        
        # DEBUG: Print structure to debug empty content
        print_colored(f"DEBUG keys: {list(detail.keys())}", COLOR_YELLOW)

        detail_note = _get_note_card(detail)
        alt_note = detail.get("note") if isinstance(detail.get("note"), dict) else {}

        detail_title = _pick_first_str(
            detail.get("display_title"),
            detail.get("displayTitle"),
            detail_note.get("display_title"),
            detail_note.get("displayTitle"),
            detail_note.get("title"),
            alt_note.get("title"),
        )
        detail_content = _pick_first_str(
            detail.get("desc"),
            detail.get("content"),
            detail_note.get("desc"),
            detail_note.get("content"),
            alt_note.get("desc"),
            alt_note.get("content"),
        )
        detail_token = _pick_first_str(
            detail.get("xsec_token"),
            detail.get("xsecToken"),
            detail_note.get("xsec_token"),
            detail_note.get("xsecToken"),
            alt_note.get("xsec_token"),
            alt_note.get("xsecToken"),
        )
        xsec_token = detail_token or candidate.xsec_token

        title = detail_title or candidate.title or "无标题"
        content = detail_content or ""

        return FeedDetail(
            feed_id=candidate.feed_id,
            xsec_token=xsec_token,
            title=title,
            content=content,
            raw=detail,
        )

    def prompt_comment(self, detail: FeedDetail) -> CommentDecision:
        mode = self.config.comment_mode.mode
        if mode == "fixed":
            candidates = self.config.comment_mode.fixed_content
            if not candidates:
                print_colored("[跳过] fixed_content 为空，无法自动评论", COLOR_YELLOW)
                return CommentDecision(action=ACTION_SKIP)
            
            # Pick a random one
            fixed_content = random.choice(candidates).strip()
            title = _clean_single_line(detail.title)
            print(f"[自动] 正在评论《{title}》: {fixed_content}")
            return CommentDecision(action=ACTION_SEND, content=fixed_content)

        print_colored("请输入评论 (回车跳过/q退出):", COLOR_GREEN)
        user_input = input().strip()
        if not user_input:
            return CommentDecision(action=ACTION_SKIP)
        if user_input.lower() == "q":
            return CommentDecision(action=ACTION_QUIT)
        return CommentDecision(action=ACTION_SEND, content=user_input)


def _extract_items(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    # Support both 'items' and 'feeds'
    items = result.get("items") or result.get("feeds")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def _unwrap_content_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    if "items" in result:
        return result
    content = result.get("content")
    if not isinstance(content, list):
        return result
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return result


def _is_note_item(item: Dict[str, Any]) -> bool:
    model_type = item.get("modelType") or item.get("model_type")
    if not model_type:
        return True
    return str(model_type).lower() == "note"


def _get_note_card(item: Dict[str, Any]) -> Dict[str, Any]:
    # Check for wrapped 'data' key first (common in detail response)
    if "data" in item and isinstance(item["data"], dict):
        item = item["data"]

    if isinstance(item.get("note_card"), dict):
        return item["note_card"]
    if isinstance(item.get("noteCard"), dict):
        return item["noteCard"]
    # Sometimes detail IS the note card directly or contains title/desc directly
    return item

def _normalize_id(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _pick_first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return ""


def _is_excluded_title(title: str) -> bool:
    if not title:
        return False
    title_lower = title.lower()
    for keyword in EXCLUDE_KEYWORDS:
        if keyword.lower() in title_lower:
            return True
    return False


def _clean_single_line(text: str) -> str:
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " / ")
    return cleaned.strip()
