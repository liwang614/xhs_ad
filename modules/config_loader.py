from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

COLOR_RESET = "\033[0m"
COLOR_YELLOW = "\033[33m"
COLOR_GREEN = "\033[32m"
COLOR_RED = "\033[31m"
COLOR_WHITE = "\033[37m"

SORT_TYPE_MAP = {
    "general": "综合",
    "latest": "最新",
    "popularity": "最多点赞",
}

FILTER_DATE_MAP = {
    "1d": "一天内",
    "7d": "一周内",
    "180d": "半年内",
}

DEFAULT_SORT_TYPE = "general"
DEFAULT_FILTER_DATE = "1d"
DEFAULT_MAX_COUNT_TOTAL = 10
DEFAULT_INTERVAL_RANGE = (5, 10)
DEFAULT_AUTO_LIKE = True
DEFAULT_COMMENT_MODE = "interactive"
DEFAULT_FIXED_CONTENT = ""


def print_colored(text: str, color_code: str = COLOR_WHITE) -> None:
    print(f"{color_code}{text}{COLOR_RESET}")


def _warn(message: str) -> None:
    print_colored(f"[警告] {message}", COLOR_YELLOW)


@dataclass(frozen=True)
class SearchConfig:
    keywords: List[str]
    sort_type: str
    filter_date: str


@dataclass(frozen=True)
class ExecutionConfig:
    max_count_total: int
    interval_range: Tuple[int, int]
    auto_like: bool
    max_comments_per_round: int
    round_interval: int
    retry_interval: int


@dataclass(frozen=True)
class CommentModeConfig:
    mode: str
    fixed_content: List[str]


@dataclass(frozen=True)
class AppConfig:
    search: SearchConfig
    execution: ExecutionConfig
    comment_mode: CommentModeConfig


def load_config(path: str = "config.json") -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        _warn("配置文件根结构无效，已使用默认配置")
        raw = {}

    search_raw = raw.get("search") if isinstance(raw.get("search"), dict) else {}
    execution_raw = raw.get("execution") if isinstance(raw.get("execution"), dict) else {}
    comment_raw = raw.get("comment_mode") if isinstance(raw.get("comment_mode"), dict) else {}

    keywords = _normalize_keywords(search_raw.get("keywords"))
    sort_type = _normalize_sort_type(search_raw.get("sort_type"))
    filter_date = _normalize_filter_date(search_raw.get("filter_date"))

    max_count_total = _normalize_positive_int(
        execution_raw.get("max_count_total"),
        DEFAULT_MAX_COUNT_TOTAL,
        "max_count_total",
    )
    interval_range = _normalize_interval_range(execution_raw.get("interval_range"))
    auto_like = _normalize_bool(execution_raw.get("auto_like"), DEFAULT_AUTO_LIKE, "auto_like")
    
    max_comments_per_round = _normalize_positive_int(
        execution_raw.get("max_comments_per_round"),
        15,
        "max_comments_per_round"
    )
    round_interval = _normalize_positive_int(
        execution_raw.get("round_interval"),
        60,
        "round_interval"
    )
    retry_interval = _normalize_positive_int(
        execution_raw.get("retry_interval"),
        10,
        "retry_interval"
    )

    mode = _normalize_comment_mode(comment_raw.get("mode"))
    fixed_content = _normalize_fixed_content(comment_raw.get("fixed_content"))

    return AppConfig(
        search=SearchConfig(
            keywords=keywords,
            sort_type=sort_type,
            filter_date=filter_date,
        ),
        execution=ExecutionConfig(
            max_count_total=max_count_total,
            interval_range=interval_range,
            auto_like=auto_like,
            max_comments_per_round=max_comments_per_round,
            round_interval=round_interval,
            retry_interval=retry_interval,
        ),
        comment_mode=CommentModeConfig(
            mode=mode,
            fixed_content=fixed_content,
        ),
    )


def build_search_filters(search: SearchConfig) -> Dict[str, str]:
    filters = {"sort_by": SORT_TYPE_MAP[search.sort_type]}
    if search.filter_date:
        filters["publish_time"] = FILTER_DATE_MAP[search.filter_date]
    return filters


def _normalize_keywords(value: Any) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        _warn("配置项 keywords 无效，已回退为空列表")
        return []
    out: List[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text:
            out.append(text)
    return out


def _normalize_sort_type(value: Any) -> str:
    if value is None:
        return DEFAULT_SORT_TYPE
    if not isinstance(value, str):
        _warn("配置项 sort_type 无效，已回退为 'general'")
        return DEFAULT_SORT_TYPE
    if not value:
        return DEFAULT_SORT_TYPE
    if value not in SORT_TYPE_MAP:
        _warn("配置项 sort_type 无效，已回退为 'general'")
        return DEFAULT_SORT_TYPE
    return value


def _normalize_filter_date(value: Any) -> str:
    if value is None:
        return DEFAULT_FILTER_DATE
    if not isinstance(value, str):
        _warn("配置项 filter_date 无效，已回退为 '1d'")
        return DEFAULT_FILTER_DATE
    if value == "":
        return ""
    if value not in FILTER_DATE_MAP:
        _warn("配置项 filter_date 无效，已回退为 '1d'")
        return DEFAULT_FILTER_DATE
    return value


def _normalize_positive_int(value: Any, default: int, name: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        _warn(f"配置项 {name} 无效，已回退为 {default}")
        return default
    try:
        num = int(value)
    except (TypeError, ValueError):
        _warn(f"配置项 {name} 无效，已回退为 {default}")
        return default
    if num <= 0:
        _warn(f"配置项 {name} 无效，已回退为 {default}")
        return default
    return num


def _normalize_interval_range(value: Any) -> Tuple[int, int]:
    if value is None:
        return DEFAULT_INTERVAL_RANGE
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        _warn("配置项 interval_range 无效，已回退为 [5, 10]")
        return DEFAULT_INTERVAL_RANGE
    try:
        start = int(value[0])
        end = int(value[1])
    except (TypeError, ValueError):
        _warn("配置项 interval_range 无效，已回退为 [5, 10]")
        return DEFAULT_INTERVAL_RANGE
    if start < 0 or end < 0:
        _warn("配置项 interval_range 无效，已回退为 [5, 10]")
        return DEFAULT_INTERVAL_RANGE
    if start > end:
        _warn("配置项 interval_range 顺序错误，已自动交换")
        start, end = end, start
    return (start, end)


def _normalize_bool(value: Any, default: bool, name: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    _warn(f"配置项 {name} 无效，已回退为 {default}")
    return default


def _normalize_comment_mode(value: Any) -> str:
    if value is None:
        return DEFAULT_COMMENT_MODE
    if not isinstance(value, str):
        _warn("配置项 mode 无效，已回退为 'interactive'")
        return DEFAULT_COMMENT_MODE
    mode = value.strip().lower()
    if mode not in ("interactive", "fixed"):
        _warn("配置项 mode 无效，已回退为 'interactive'")
        return DEFAULT_COMMENT_MODE
    return mode


def _normalize_fixed_content(value: Any) -> List[str]:
    if value is None:
        return [DEFAULT_FIXED_CONTENT] if DEFAULT_FIXED_CONTENT else []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    _warn("配置项 fixed_content 无效，已回退为空列表")
    return []