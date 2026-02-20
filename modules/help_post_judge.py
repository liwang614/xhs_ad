from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests


DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "claude": "https://api.anthropic.com/v1",
}

DEFAULT_NOTE_PROMPT_TEMPLATE = (
    "你是内容审核助手。请判断以下小红书笔记是否是求助帖。\n"
    "规则：作者明确提问、征求建议、请求解决方案、求推荐、求经验，判定为求助帖。\n"
    "经验分享、展示、广告、泛讨论不算求助帖。\n"
    "标题：{{title}}\n"
    "正文：{{content}}\n\n"
    "只输出 JSON：{\"is_help_post\": 0 或 1}"
)
DEFAULT_COMMENT_PROMPT_TEMPLATE = (
    "你是内容审核助手。请判断以下小红书评论内容是否是求助内容。\n"
    "规则：明确提问、征求建议、请求解决方案、求推荐、求经验，判定为求助。\n"
    "经验分享、展示、广告、纯情绪表达、泛讨论不算求助。\n"
    "评论内容：{{content}}\n\n"
    "只输出 JSON：{\"is_help_post\": 0 或 1}"
)


class HelpPostJudgeError(RuntimeError):
    pass


class AIHelpPostJudge:
    def __init__(
        self,
        provider: str,
        model: str,
        *,
        base_url: Optional[str] = None,
        timeout: int = 30,
        log_path: str = "logs/help_post_judge_errors.log",
        note_prompt_template: Optional[str] = None,
        comment_prompt_template: Optional[str] = None,
    ) -> None:
        provider_value = (provider or "").strip().lower()
        if provider_value not in ("openai", "gemini", "claude"):
            raise HelpPostJudgeError(f"unsupported provider: {provider}")
        if not (model or "").strip():
            raise HelpPostJudgeError("model is required")

        self.provider = provider_value
        self.model = model.strip()
        self.base_url = (base_url or DEFAULT_BASE_URLS[self.provider]).rstrip("/")
        self.timeout = timeout
        self.log_path = log_path
        self.note_prompt_template = (
            note_prompt_template.strip() if isinstance(note_prompt_template, str) and note_prompt_template.strip()
            else DEFAULT_NOTE_PROMPT_TEMPLATE
        )
        self.comment_prompt_template = (
            comment_prompt_template.strip()
            if isinstance(comment_prompt_template, str) and comment_prompt_template.strip()
            else DEFAULT_COMMENT_PROMPT_TEMPLATE
        )
        self.api_key = _resolve_api_key(self.provider)

    def classify(self, title: str, desc: str) -> int:
        prompt = _build_prompt(
            title=title,
            desc=desc,
            note_prompt_template=self.note_prompt_template,
            comment_prompt_template=self.comment_prompt_template,
        )
        text = self._call_by_provider(prompt)

        parsed = _safe_parse_json(text)
        if not isinstance(parsed, dict):
            raise HelpPostJudgeError(f"invalid json output: {text[:200]}")

        value = parsed.get("is_help_post")
        normalized = _normalize_is_help_post(value)
        if normalized is None:
            raise HelpPostJudgeError(f"invalid is_help_post value: {value!r}")
        return normalized

    def classify_row(self, row_id: int, title: str, desc: str) -> Optional[int]:
        try:
            return self.classify(title=title, desc=desc)
        except Exception as exc:
            self.log_error(row_id=row_id, error=str(exc))
            return None

    def generate_text(self, prompt: str) -> str:
        text = self._call_by_provider(prompt)
        generated = (text or "").strip()
        if not generated:
            raise HelpPostJudgeError("empty generated text")
        return generated

    def generate_comment(self, *, title: str, content: str, prompt_template: str) -> str:
        prompt = _render_prompt_template(prompt_template, title=title or "", content=content or "")
        return self.generate_text(prompt)

    def _call_by_provider(self, prompt: str) -> str:
        if self.provider == "openai":
            return self._call_openai(prompt)
        if self.provider == "gemini":
            return self._call_gemini(prompt)
        return self._call_claude(prompt)

    def log_error(self, row_id: int, error: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = (
            f"{ts}\trow_id={row_id}\tprovider={self.provider}\t"
            f"model={self.model}\terror={error}\n"
        )
        path = Path(self.log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(message)

    def _call_openai(self, prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是严谨的中文内容分类器。输出必须是 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        _raise_for_status(resp)
        data = resp.json()

        try:
            content = data["choices"][0]["message"]["content"]
        except Exception as exc:  # pragma: no cover - defensive
            raise HelpPostJudgeError(f"openai response format error: {data}") from exc
        return _stringify_content(content)

    def _call_gemini(self, prompt: str) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0},
        }
        resp = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        _raise_for_status(resp)
        data = resp.json()

        try:
            parts = data["candidates"][0]["content"]["parts"]
        except Exception as exc:  # pragma: no cover - defensive
            raise HelpPostJudgeError(f"gemini response format error: {data}") from exc

        texts = []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
        if not texts:
            raise HelpPostJudgeError(f"gemini empty text: {data}")
        return "\n".join(texts)

    def _call_claude(self, prompt: str) -> str:
        url = f"{self.base_url}/messages"
        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": 200,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
        resp = requests.post(
            url,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        _raise_for_status(resp)
        data = resp.json()

        try:
            content = data["content"]
        except Exception as exc:  # pragma: no cover - defensive
            raise HelpPostJudgeError(f"claude response format error: {data}") from exc

        texts = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    texts.append(item["text"])
        if not texts:
            raise HelpPostJudgeError(f"claude empty text: {data}")
        return "\n".join(texts)


def _resolve_api_key(provider: str) -> str:
    shared_key = os.getenv("LLM_API_KEY", "").strip()
    if shared_key:
        return shared_key

    env_map = {
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
    }
    env_name = env_map[provider]
    key = os.getenv(env_name, "").strip()
    if key:
        return key
    raise HelpPostJudgeError(f"missing api key: {env_name}")


def _build_prompt(
    title: str,
    desc: str,
    *,
    note_prompt_template: str,
    comment_prompt_template: str,
) -> str:
    title_text = (title or "").strip()
    content_text = (desc or "").strip()
    if not title_text:
        return _render_prompt_template(comment_prompt_template, title_text, content_text)

    return _render_prompt_template(note_prompt_template, title_text, content_text)


def _render_prompt_template(template: str, title: str, content: str) -> str:
    title_text = title or "(空)"
    content_text = content or "(空)"
    return template.replace("{{title}}", title_text).replace("{{content}}", content_text)


def _normalize_is_help_post(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return 1 if value == 1 else 0 if value == 0 else None
    if isinstance(value, str):
        text = value.strip()
        if text in ("0", "1"):
            return int(text)
    return None


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                out.append(item["text"])
        return "\n".join(out)
    return str(content)


def _raise_for_status(resp: requests.Response) -> None:
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        body = resp.text[:300] if resp.text else ""
        raise HelpPostJudgeError(f"http {resp.status_code}: {body}") from exc


def _safe_parse_json(text: str) -> Optional[Dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return None

    # Raw JSON
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    # Markdown fenced JSON
    if "```" in raw:
        for chunk in raw.split("```"):
            part = chunk.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                obj = json.loads(part)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue

    # Fallback: first {...} segment
    left = raw.find("{")
    right = raw.rfind("}")
    if left != -1 and right != -1 and right > left:
        snippet = raw[left : right + 1]
        try:
            obj = json.loads(snippet)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None
