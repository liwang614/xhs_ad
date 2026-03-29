from __future__ import annotations

from typing import Protocol

from .database_store import AnalysisResult, PendingAnalysisRecord


class AnalysisProvider(Protocol):
    """Provider interface for analyzing a single message.

    Implementations must accept a PendingAnalysisRecord and return an
    AnalysisResult.  Raise any exception to signal failure -- the
    pipeline will catch it and mark the record as failed.
    """

    @property
    def name(self) -> str: ...

    def analyze(self, record: PendingAnalysisRecord) -> AnalysisResult: ...
