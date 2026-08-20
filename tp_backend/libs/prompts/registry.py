"""Prompt records. `version` is what lands in extractions.prompt_version — bump it when the text
changes, or re-extraction will silently reuse the older result."""

from dataclasses import dataclass

GEMINI_FLASH_LITE = "gemini-3.5-flash-lite"


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    model: str
    template: str
    schema: dict

    @property
    def version_key(self) -> str:
        return f"{self.name}/{self.version}"

    def render(self, **kw) -> str:
        return self.template.format(**kw)
