"""Transcript fetching, ported from spikes/videos_transcribing/youtube_llm_pipeline.py.

youtube-transcript-api runs on requests, not our httpx client, so the OS trust store is injected here
the way libs/http.py does it — corporate TLS interception breaks it otherwise.
"""

import logging

import truststore
import youtube_transcript_api as yta

from libs.db.enums import ErrorCode
from tp_ingestions.errors import TaskError

truststore.inject_into_ssl()

log = logging.getLogger("youtube.transcript")

WINDOW = 25


def _errors(*names: str) -> tuple[type[BaseException], ...]:
    """The library's exception module has moved between major versions, so resolve by name."""
    return tuple(e for e in (getattr(yta, n, None) for n in names) if isinstance(e, type))


# 1.x dropped TooManyRequests in favour of RequestBlocked/IpBlocked; PoTokenRequired is what a
# datacenter IP gets, which is an environment problem and so must stay retryable.
PERMANENT = _errors("TranscriptsDisabled", "NoTranscriptFound", "VideoUnavailable",
                    "VideoUnplayable", "InvalidVideoId", "AgeRestricted")
RATE_LIMITED = _errors("TooManyRequests", "RequestBlocked", "IpBlocked", "PoTokenRequired")


def stamp(sec: float) -> str:
    """Seconds to MM:SS."""
    return f"{int(sec) // 60:02d}:{int(sec) % 60:02d}"


def to_prompt_text(segments: list[tuple[float, str]], window: int = WINDOW) -> str:
    """Collapse segments into timestamped paragraphs so the model can cite moments."""
    lines, buf, t0 = [], [], None
    for start, text in segments:
        if t0 is None:
            t0 = start
        buf.append(text)
        if start - t0 >= window:
            lines.append(f"[{stamp(t0)}] " + " ".join(buf))
            buf, t0 = [], None
    if buf:
        lines.append(f"[{stamp(t0 or 0)}] " + " ".join(buf))
    return "\n".join(lines)


def fetch_transcript(video_id: str) -> list[tuple[float, str]]:
    """Segments as (start_seconds, text). Raises a classified TaskError, never a library one."""
    try:
        segments = list(yta.YouTubeTranscriptApi().fetch(video_id))
    except PERMANENT as e:
        raise TaskError(ErrorCode.PERMANENT, f"transcript {video_id}: {type(e).__name__}") from e
    except RATE_LIMITED as e:
        raise TaskError(ErrorCode.RATE_LIMITED, f"transcript {video_id}: {type(e).__name__}") from e
    except Exception as e:
        raise TaskError(ErrorCode.TRANSIENT, f"transcript {video_id}: {type(e).__name__}: {e}") from e
    return [(s.start, s.text) for s in segments]
