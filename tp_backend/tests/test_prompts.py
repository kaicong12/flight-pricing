"""Pins each prompt to its version. Editing a template without bumping its version fails here,
which is the only thing that keeps extractions.prompt_version meaningful."""

import hashlib
import json

from libs.db.models import Extraction
from libs.prompts import PROMPTS

DIGESTS = {
    "rednote_ocr": "57de1d4b19894962",
    "rednote_prescreen": "8bad0dc0352eec68",
    "rednote_text": "ba283dbfdd4032f8",
    "youtube_transcript": "052b6fe5e1ade65a",
}


def digest(prompt) -> str:
    blob = prompt.template + json.dumps(prompt.schema, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def test_every_prompt_is_pinned():
    assert set(PROMPTS) == set(DIGESTS)


def test_templates_have_not_changed_without_a_version_bump():
    drifted = {name: digest(p) for name, p in PROMPTS.items() if digest(p) != DIGESTS[name]}
    assert not drifted, f"bump the version and update DIGESTS for: {drifted}"


def test_version_key_fits_the_prompt_version_column():
    limit = Extraction.__table__.c.prompt_version.type.length
    assert all(len(p.version_key) <= limit for p in PROMPTS.values())


def test_rendering_fills_every_placeholder():
    rendered = PROMPTS["rednote_text"].render(city="Helsinki", title="t", body="b")
    assert "Helsinki" in rendered
    assert "{" not in rendered.replace("{}", "")
