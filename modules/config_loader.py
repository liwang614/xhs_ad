from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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
DEFAULT_COMMENT_MODE = "interactive"
DEFAULT_FIXED_CONTENT = ""
DEFAULT_AI_JUDGE_MODE = "manual"
DEFAULT_AI_PROVIDER = "openai"
DEFAULT_AI_JUDGE_MODEL = "gpt-4o-mini"
DEFAULT_AI_GENERATE_MODEL = "gpt-4o-mini"
DEFAULT_AI_BATCH_SIZE = 50
DEFAULT_AI_TIMEOUT = 30
DEFAULT_AI_TABLES = ["xhs_note"]
DEFAULT_AI_GENERATE_REPLY_MODE = "manual"
DEFAULT_AI_REPLY_TARGET_IDS: List[int] = []
DEFAULT_AI_OVERWRITE_GENERATED_COMMENT = False
DEFAULT_AI_NOTE_PROMPT_TEMPLATE = (
    "你是内容审核助手。请判断以下小红书笔记是否是求助帖。\n"
    "规则：作者明确提问、征求建议、请求解决方案、求推荐、求经验，判定为求助帖。\n"
    "经验分享、展示、广告、泛讨论不算求助帖。\n"
    "标题：{{title}}\n"
    "正文：{{content}}\n\n"
    "只输出 JSON：{\"is_help_post\": 0 或 1}"
)
DEFAULT_AI_COMMENT_PROMPT_TEMPLATE = (
    "你是内容审核助手。请判断以下小红书评论内容是否是求助内容。\n"
    "规则：明确提问、征求建议、请求解决方案、求推荐、求经验，判定为求助。\n"
    "经验分享、展示、广告、纯情绪表达、泛讨论不算求助。\n"
    "评论内容：{{content}}\n\n"
    "只输出 JSON：{\"is_help_post\": 0 或 1}"
)
DEFAULT_AI_GENERATE_PROMPT_TEMPLATE = (
    "你是小红书评论助手。请基于给定内容生成一条自然、简洁、礼貌的中文回复。\n"
    "不要夸张营销，不要包含联系方式，不要输出解释。\n"
    "标题：{{title}}\n"
    "内容：{{content}}\n\n"
    "只输出最终回复文案。"
)
DEFAULT_MCP_URL = "http://127.0.0.1:18060/mcp"
DEFAULT_MCP_REPLY_TOOL_NAME = "reply_comment_in_feed"

DEFAULT_ANALYSIS_ENABLED = True
DEFAULT_ANALYSIS_PROVIDER = "codexexec"
DEFAULT_ANALYSIS_COMMAND = "codex"
DEFAULT_ANALYSIS_TIMEOUT = 120
DEFAULT_ANALYSIS_BATCH_SIZE = 20
DEFAULT_ANALYSIS_TABLES = ["xhs_note_comment"]


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
    max_comments_per_round: int
    round_interval: int


@dataclass(frozen=True)
class CommentModeConfig:
    mode: str
    fixed_content: List[str]


@dataclass(frozen=True)
class AiJudgeConfig:
    mode: str
    provider: str
    judge_model: str
    generate_model: str
    generate_prompt_template: str
    generate_reply_mode: str
    reply_target_ids: List[int]
    overwrite_generated_comment: bool
    batch_size: int
    timeout: int
    base_url: Optional[str]
    tables: List[str]
    note_prompt_template: str
    comment_prompt_template: str

    @property
    def model(self) -> str:
        # Backward-compatible alias used by older call sites.
        return self.judge_model


@dataclass(frozen=True)
class AnalysisConfig:
    enabled: bool
    provider: str
    command: str
    timeout: int
    batch_size: int
    tables: List[str]


@dataclass(frozen=True)
class AppConfig:
    search: SearchConfig
    execution: ExecutionConfig
    comment_mode: CommentModeConfig
    ai_judge: AiJudgeConfig
    mcp: "McpConfig"
    analysis: AnalysisConfig


@dataclass(frozen=True)
class McpConfig:
    url: str
    reply_tool_name: str


def load_config(path: str = "config.json") -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        _warn("配置文件根结构无效，已使用默认配置")
        raw = {}

    search_raw = raw.get("search") if isinstance(raw.get("search"), dict) else {}
    execution_raw = raw.get("execution") if isinstance(raw.get("execution"), dict) else {}
    comment_raw = raw.get("comment_mode") if isinstance(raw.get("comment_mode"), dict) else {}
    ai_judge_raw = raw.get("ai_judge") if isinstance(raw.get("ai_judge"), dict) else {}
    mcp_raw = raw.get("mcp") if isinstance(raw.get("mcp"), dict) else {}
    analysis_raw = raw.get("analysis") if isinstance(raw.get("analysis"), dict) else {}

    keywords = _normalize_keywords(search_raw.get("keywords"))
    sort_type = _normalize_sort_type(search_raw.get("sort_type"))
    filter_date = _normalize_filter_date(search_raw.get("filter_date"))

    max_count_total = _normalize_positive_int(
        execution_raw.get("max_count_total"),
        DEFAULT_MAX_COUNT_TOTAL,
        "max_count_total",
    )
    interval_range = _normalize_interval_range(execution_raw.get("interval_range"))
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

    mode = _normalize_comment_mode(comment_raw.get("mode"))
    fixed_content = _normalize_fixed_content(comment_raw.get("fixed_content"))
    ai_mode = _normalize_ai_mode(ai_judge_raw.get("mode"))
    ai_provider = _normalize_ai_provider(ai_judge_raw.get("provider"))
    ai_model_legacy = ai_judge_raw.get("model")
    ai_judge_model = _normalize_non_empty_str(
        ai_judge_raw.get("judge_model") if ai_judge_raw.get("judge_model") is not None else ai_model_legacy,
        DEFAULT_AI_JUDGE_MODEL,
        "ai_judge.judge_model",
    )
    ai_generate_model = _normalize_non_empty_str(
        ai_judge_raw.get("generate_model"),
        ai_judge_model or DEFAULT_AI_GENERATE_MODEL,
        "ai_judge.generate_model",
    )
    ai_generate_prompt_template = _normalize_prompt_template(
        ai_judge_raw.get("generate_prompt_template"),
        DEFAULT_AI_GENERATE_PROMPT_TEMPLATE,
        "ai_judge.generate_prompt_template",
    )
    ai_generate_reply_mode = _normalize_generate_reply_mode(ai_judge_raw.get("generate_reply_mode"))
    ai_reply_target_ids = _normalize_int_list(ai_judge_raw.get("reply_target_ids"), "ai_judge.reply_target_ids")
    ai_overwrite_generated_comment = _normalize_bool(
        ai_judge_raw.get("overwrite_generated_comment"),
        DEFAULT_AI_OVERWRITE_GENERATED_COMMENT,
        "ai_judge.overwrite_generated_comment",
    )
    ai_batch_size = _normalize_positive_int(
        ai_judge_raw.get("batch_size"),
        DEFAULT_AI_BATCH_SIZE,
        "ai_judge.batch_size",
    )
    ai_timeout = _normalize_positive_int(
        ai_judge_raw.get("timeout"),
        DEFAULT_AI_TIMEOUT,
        "ai_judge.timeout",
    )
    ai_base_url = _normalize_optional_str(ai_judge_raw.get("base_url"))
    ai_tables_raw = ai_judge_raw["tables"] if "tables" in ai_judge_raw else ai_judge_raw.get("table")
    ai_tables = _normalize_ai_tables(ai_tables_raw)
    ai_note_prompt_template = _normalize_prompt_template(
        ai_judge_raw.get("note_prompt_template"),
        DEFAULT_AI_NOTE_PROMPT_TEMPLATE,
        "ai_judge.note_prompt_template",
    )
    ai_comment_prompt_template = _normalize_prompt_template(
        ai_judge_raw.get("comment_prompt_template"),
        DEFAULT_AI_COMMENT_PROMPT_TEMPLATE,
        "ai_judge.comment_prompt_template",
    )
    mcp_url = _normalize_non_empty_str(mcp_raw.get("url"), DEFAULT_MCP_URL, "mcp.url")
    mcp_reply_tool_name = _normalize_reply_tool_name(mcp_raw.get("reply_tool_name"))

    analysis_enabled = _normalize_bool(
        analysis_raw.get("enabled"), DEFAULT_ANALYSIS_ENABLED, "analysis.enabled"
    )
    analysis_provider = _normalize_non_empty_str(
        analysis_raw.get("provider"), DEFAULT_ANALYSIS_PROVIDER, "analysis.provider"
    )
    analysis_command = _normalize_non_empty_str(
        analysis_raw.get("command"), DEFAULT_ANALYSIS_COMMAND, "analysis.command"
    )
    analysis_timeout = _normalize_positive_int(
        analysis_raw.get("timeout"), DEFAULT_ANALYSIS_TIMEOUT, "analysis.timeout"
    )
    analysis_batch_size = _normalize_positive_int(
        analysis_raw.get("batch_size"), DEFAULT_ANALYSIS_BATCH_SIZE, "analysis.batch_size"
    )
    analysis_tables = _normalize_ai_tables(analysis_raw.get("tables") if analysis_raw.get("tables") is not None else DEFAULT_ANALYSIS_TABLES)

    return AppConfig(
        search=SearchConfig(
            keywords=keywords,
            sort_type=sort_type,
            filter_date=filter_date,
        ),
        execution=ExecutionConfig(
            max_count_total=max_count_total,
            interval_range=interval_range,
            max_comments_per_round=max_comments_per_round,
            round_interval=round_interval,
        ),
        comment_mode=CommentModeConfig(
            mode=mode,
            fixed_content=fixed_content,
        ),
        ai_judge=AiJudgeConfig(
            mode=ai_mode,
            provider=ai_provider,
            judge_model=ai_judge_model,
            generate_model=ai_generate_model,
            generate_prompt_template=ai_generate_prompt_template,
            generate_reply_mode=ai_generate_reply_mode,
            reply_target_ids=ai_reply_target_ids,
            overwrite_generated_comment=ai_overwrite_generated_comment,
            batch_size=ai_batch_size,
            timeout=ai_timeout,
            base_url=ai_base_url,
            tables=ai_tables,
            note_prompt_template=ai_note_prompt_template,
            comment_prompt_template=ai_comment_prompt_template,
        ),
        mcp=McpConfig(
            url=mcp_url,
            reply_tool_name=mcp_reply_tool_name,
        ),
        analysis=AnalysisConfig(
            enabled=analysis_enabled,
            provider=analysis_provider,
            command=analysis_command,
            timeout=analysis_timeout,
            batch_size=analysis_batch_size,
            tables=analysis_tables,
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


def _normalize_ai_mode(value: Any) -> str:
    if value is None:
        return DEFAULT_AI_JUDGE_MODE
    if not isinstance(value, str):
        _warn("配置项 ai_judge.mode 无效，已回退为 'manual'")
        return DEFAULT_AI_JUDGE_MODE
    mode = value.strip().lower()
    if mode not in ("manual", "auto", "immediate", "batch"):
        _warn("配置项 ai_judge.mode 无效，已回退为 'manual'")
        return DEFAULT_AI_JUDGE_MODE
    return mode


def _normalize_ai_provider(value: Any) -> str:
    if value is None:
        return DEFAULT_AI_PROVIDER
    if not isinstance(value, str):
        _warn("配置项 ai_judge.provider 无效，已回退为 'openai'")
        return DEFAULT_AI_PROVIDER
    provider = value.strip().lower()
    if provider not in ("openai", "gemini", "claude"):
        _warn("配置项 ai_judge.provider 无效，已回退为 'openai'")
        return DEFAULT_AI_PROVIDER
    return provider


def _normalize_generate_reply_mode(value: Any) -> str:
    if value is None:
        return DEFAULT_AI_GENERATE_REPLY_MODE
    if not isinstance(value, str):
        _warn("配置项 ai_judge.generate_reply_mode 无效，已回退为 'manual'")
        return DEFAULT_AI_GENERATE_REPLY_MODE
    mode = value.strip().lower()
    if mode not in ("manual", "generate", "reply", "all"):
        _warn("配置项 ai_judge.generate_reply_mode 无效，已回退为 'manual'")
        return DEFAULT_AI_GENERATE_REPLY_MODE
    return mode


def _normalize_int_list(value: Any, name: str) -> List[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        _warn(f"配置项 {name} 无效，已回退为空列表")
        return []
    out: List[int] = []
    for item in value:
        if isinstance(item, bool):
            continue
        try:
            num = int(item)
        except (TypeError, ValueError):
            continue
        if num <= 0:
            continue
        if num not in out:
            out.append(num)
    return out


def _normalize_bool(value: Any, default: bool, name: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    _warn(f"配置项 {name} 无效，已回退为 {default}")
    return default


def _normalize_non_empty_str(value: Any, default: str, name: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        _warn(f"配置项 {name} 无效，已回退为 '{default}'")
        return default
    text = value.strip()
    if not text:
        _warn(f"配置项 {name} 为空，已回退为 '{default}'")
        return default
    return text


def _normalize_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        _warn("配置项 ai_judge.base_url 无效，已忽略")
        return None
    text = value.strip()
    return text if text else None


def _normalize_ai_tables(value: Any) -> List[str]:
    raw_items: List[str] = []
    if value is None:
        return list(DEFAULT_AI_TABLES)
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = [v for v in value if isinstance(v, str)]
    else:
        _warn("配置项 ai_judge.tables 无效，已回退为 ['xhs_note']")
        return list(DEFAULT_AI_TABLES)

    out: List[str] = []
    for item in raw_items:
        table = item.strip()
        if not table:
            continue
        if not _is_valid_table_name(table):
            _warn(f"配置项 ai_judge.tables 包含非法表名：{table}，已忽略")
            continue
        if table not in out:
            out.append(table)

    if not out:
        _warn("配置项 ai_judge.tables 为空，已回退为 ['xhs_note']")
        return list(DEFAULT_AI_TABLES)
    return out


def _is_valid_table_name(name: str) -> bool:
    for ch in name:
        if not (ch.isalnum() or ch == "_"):
            return False
    return True


def _normalize_prompt_template(value: Any, default: str, name: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        _warn(f"配置项 {name} 无效，已回退为默认模板")
        return default
    text = value.strip()
    if not text:
        _warn(f"配置项 {name} 为空，已回退为默认模板")
        return default
    return text


def _normalize_reply_tool_name(value: Any) -> str:
    if value is None:
        return DEFAULT_MCP_REPLY_TOOL_NAME
    if not isinstance(value, str):
        _warn(f"配置项 mcp.reply_tool_name 无效，已强制使用 '{DEFAULT_MCP_REPLY_TOOL_NAME}'")
        return DEFAULT_MCP_REPLY_TOOL_NAME
    text = value.strip()
    if not text:
        return DEFAULT_MCP_REPLY_TOOL_NAME
    if text != DEFAULT_MCP_REPLY_TOOL_NAME:
        _warn(f"配置项 mcp.reply_tool_name 已强制使用 '{DEFAULT_MCP_REPLY_TOOL_NAME}'")
    return DEFAULT_MCP_REPLY_TOOL_NAME
