from __future__ import annotations

from dataclasses import dataclass
import random
from typing import List

from .config_loader import COLOR_GREEN, COLOR_YELLOW, AppConfig, print_colored
from .database_store import NoteRecord

EXCLUDE_KEYWORDS = ["广告", "商单", "推广"]

ACTION_SEND = "send"
ACTION_SKIP = "skip"
ACTION_QUIT = "quit"


@dataclass(frozen=True)
class CommentDecision:
    action: str
    content: str = ""


class LogicProcessor:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def filter_candidates(self, notes: List[NoteRecord]) -> List[NoteRecord]:
        out: List[NoteRecord] = []
        for note in notes:
            title = note.title or ""
            if self._is_excluded_title(title):
                continue
            out.append(note)
        return out

    def prompt_comment(self, note: NoteRecord) -> CommentDecision:
        mode = self.config.comment_mode.mode
        if mode == "fixed":
            candidates = self.config.comment_mode.fixed_content
            if not candidates:
                print_colored("[跳过] fixed_content 为空，无法自动评论", COLOR_YELLOW)
                return CommentDecision(action=ACTION_SKIP)

            fixed_content = random.choice(candidates).strip()
            title = _clean_single_line(note.title)
            print(f"[自动] 记录评论《{title}》: {fixed_content}")
            return CommentDecision(
                action=ACTION_SEND,
                content=fixed_content,
            )

        print_colored("请输入评论 (回车跳过/q退出):", COLOR_GREEN)
        user_input = input().strip()
        if not user_input:
            return CommentDecision(action=ACTION_SKIP)
        if user_input.lower() == "q":
            return CommentDecision(action=ACTION_QUIT)
        return CommentDecision(action=ACTION_SEND, content=user_input)

    @staticmethod
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
