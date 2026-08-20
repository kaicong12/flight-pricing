"""Prompt records. `version` is what lands in extractions.prompt_version — bump it when the text
changes, or re-extraction will silently reuse the older result."""

from dataclasses import dataclass

from libs.settings import settings


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    template: str
    schema: dict

    @property
    def model(self) -> str:
        """Read at call time, not import time, so GEMINI_MODEL can be swapped without a code change."""
        return settings().gemini_model

    @property
    def version_key(self) -> str:
        return f"{self.name}/{self.version}"

    def render(self, **kw) -> str:
        return self.template.format(**kw)
