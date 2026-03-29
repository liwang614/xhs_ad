from __future__ import annotations

from typing import Dict, Optional

from .analysis_provider import AnalysisProvider


VALID_OPPORTUNITY_TYPES = ("solution_request", "none")


class AnalysisRegistry:
    """Manual registry of analysis providers.

    No dynamic plugin discovery -- providers are registered explicitly.
    """

    def __init__(self) -> None:
        self._providers: Dict[str, AnalysisProvider] = {}

    def register(self, provider: AnalysisProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> Optional[AnalysisProvider]:
        return self._providers.get(name)

    def get_default(self) -> Optional[AnalysisProvider]:
        if not self._providers:
            return None
        return next(iter(self._providers.values()))

    @property
    def provider_names(self) -> list[str]:
        return list(self._providers.keys())
