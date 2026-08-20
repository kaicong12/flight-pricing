"""The prompt registry. Every extraction records its prompt's version_key and model."""

from libs.prompts.rednote_ocr import REDNOTE_OCR
from libs.prompts.rednote_prescreen import REDNOTE_PRESCREEN
from libs.prompts.rednote_text import REDNOTE_TEXT
from libs.prompts.registry import Prompt
from libs.prompts.youtube_transcript import YOUTUBE_TRANSCRIPT

PROMPTS = {p.name: p for p in (YOUTUBE_TRANSCRIPT, REDNOTE_TEXT, REDNOTE_OCR, REDNOTE_PRESCREEN)}

__all__ = [
    "PROMPTS",
    "REDNOTE_OCR",
    "REDNOTE_PRESCREEN",
    "REDNOTE_TEXT",
    "YOUTUBE_TRANSCRIPT",
    "Prompt",
]
