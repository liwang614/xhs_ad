from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

from ..analysis_provider import AnalysisProvider
from ..database_store import AnalysisResult, PendingAnalysisRecord

PROMPT_TEMPLATE = """\
你是商业机会分析助手。请分析以下内容是否包含明确需求（求解决方案）。

标题：{title}
内容：{content}

规则：
- 作者明确提问、征求建议、请求解决方案、求推荐、求经验 → is_help_post=1, opportunity_type="solution_request"
- 经验分享、展示、广告、纯情绪表达、泛讨论 → is_help_post=0, opportunity_type="none"

只输出 JSON，不要输出其他内容：
{{"is_help_post": 0或1, "opportunity_type": "solution_request"或"none", "opportunity_summary": "一句话摘要", "demand_reason": "判定理由", "lead_score": 0到100的整数, "manual_reply_suggestion": "建议人工回复话术"}}\
"""

REQUIRED_FIELDS = (
    "is_help_post",
    "opportunity_type",
    "opportunity_summary",
    "demand_reason",
    "lead_score",
    "manual_reply_suggestion",
)


class CodexExecError(RuntimeError):
    pass


class CodexExecProvider:
    """Analysis provider that calls ``codex exec -o <output_file> <prompt>``."""

    def __init__(
        self,
        *,
        command: str = "codex",
        timeout: int = 120,
    ) -> None:
        self._command = command
        self._timeout = timeout
        resolved = shutil.which(self._command)
        if resolved is None:
            raise CodexExecError(
                f"command not found: {self._command!r}  "
                f"(ensure it is installed and on PATH)"
            )
        self._resolved_command = resolved

    @property
    def name(self) -> str:
        return "codexexec"

    def analyze(self, record: PendingAnalysisRecord) -> AnalysisResult:
        prompt = PROMPT_TEMPLATE.format(
            title=record.title or "(空)",
            content=record.content or "(空)",
        )
        raw_output = self._run_command(prompt)
        parsed = self._parse_json(raw_output)
        self._check_fields(parsed)
        return AnalysisResult(
            is_help_post=int(parsed["is_help_post"]),
            opportunity_type=str(parsed["opportunity_type"]).strip(),
            opportunity_summary=str(parsed.get("opportunity_summary") or "").strip(),
            demand_reason=str(parsed.get("demand_reason") or "").strip(),
            lead_score=int(parsed.get("lead_score") or 0),
            manual_reply_suggestion=str(parsed.get("manual_reply_suggestion") or "").strip(),
            commenter_uid=record.commenter_uid,
        )

    def _run_command(self, prompt: str) -> str:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as tmp:
            output_path = tmp.name

        # Use "-" so codex reads the prompt from stdin (avoids arg-length limits).
        cmd: List[str] = [
            self._resolved_command, "exec",
            "-o", output_path,
            "-",
        ]
        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexExecError(f"codex exec timed out after {self._timeout}s") from exc
        except OSError as exc:
            raise CodexExecError(f"codex exec execution failed: {exc}") from exc

        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()[:300]
            raise CodexExecError(
                f"codex exec exited with code {proc.returncode}: {stderr}"
            )

        try:
            with open(output_path, "r", encoding="utf-8") as f:
                output = f.read().strip()
        except FileNotFoundError:
            output = ""
        finally:
            import os
            try:
                os.unlink(output_path)
            except OSError:
                pass

        if not output:
            raise CodexExecError("codex exec returned empty output")
        return output

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        # Try direct parse first.
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

        # Try markdown fenced block.
        if "```" in text:
            for chunk in text.split("```"):
                part = chunk.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    obj = json.loads(part)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    continue

        # Fallback: first {...} segment.
        left = text.find("{")
        right = text.rfind("}")
        if left != -1 and right > left:
            try:
                obj = json.loads(text[left : right + 1])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass

        raise CodexExecError(f"failed to parse JSON from codexexec output: {text[:200]}")

    @staticmethod
    def _check_fields(data: Dict[str, Any]) -> None:
        missing = [f for f in REQUIRED_FIELDS if f not in data]
        if missing:
            raise CodexExecError(f"missing fields in codexexec output: {', '.join(missing)}")
