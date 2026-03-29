from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .analysis_provider import AnalysisProvider
from .analysis_registry import VALID_OPPORTUNITY_TYPES
from .database_store import AnalysisResult, PendingAnalysisRecord


class AnalysisPipelineError(RuntimeError):
    pass


@dataclass
class PipelineResult:
    row_id: int
    table_name: str
    success: bool
    result: Optional[AnalysisResult] = None
    error: Optional[str] = None


class AnalysisPipeline:
    """Orchestrator: read one record -> call provider -> validate -> return."""

    def __init__(self, provider: AnalysisProvider) -> None:
        self._provider = provider

    def analyze_one(self, record: PendingAnalysisRecord) -> PipelineResult:
        try:
            result = self._provider.analyze(record)
        except Exception as exc:
            return PipelineResult(
                row_id=record.row_id,
                table_name=record.table_name,
                success=False,
                error=f"provider error: {exc}",
            )

        error = _validate_result(result)
        if error:
            return PipelineResult(
                row_id=record.row_id,
                table_name=record.table_name,
                success=False,
                error=error,
            )

        if not result.commenter_uid and record.commenter_uid:
            result.commenter_uid = record.commenter_uid

        return PipelineResult(
            row_id=record.row_id,
            table_name=record.table_name,
            success=True,
            result=result,
        )


def _validate_result(result: AnalysisResult) -> Optional[str]:
    if result.is_help_post not in (0, 1):
        return f"invalid is_help_post: {result.is_help_post!r}"

    if result.opportunity_type not in VALID_OPPORTUNITY_TYPES:
        return f"invalid opportunity_type: {result.opportunity_type!r}"

    if result.is_help_post == 1 and result.opportunity_type == "none":
        return "is_help_post=1 but opportunity_type=none is contradictory"

    if result.is_help_post == 0 and result.opportunity_type != "none":
        return f"is_help_post=0 but opportunity_type={result.opportunity_type!r}"

    if result.lead_score is not None:
        try:
            score = int(result.lead_score)
        except (TypeError, ValueError):
            return f"invalid lead_score: {result.lead_score!r}"
        if score < 0 or score > 100:
            return f"lead_score out of range: {score}"
        result.lead_score = score

    return None
