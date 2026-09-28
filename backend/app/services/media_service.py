from __future__ import annotations
import re
from urllib.parse import urlparse, parse_qs

async def youtube_transcript(url: str) -> tuple[str, str]:
    """Return (title_hint, transcript) when a public transcript is available.

    This intentionally does not download the video. It uses the public transcript
    interface when available and otherwise returns empty text so the source can be
    retained as discovery-only evidence.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception:
        return "", ""
    video_id = None
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path
    if "youtu.be" in host:
        video_id = path.strip("/").split("/")[0]
    elif "youtube.com" in host:
        q = parse_qs(urlparse(url).query)
        video_id = q.get("v", [None])[0]
        if not video_id:
            m = re.search(r"/shorts/([^/?]+)", path)
            video_id = m.group(1) if m else None
    if not video_id:
        return "", ""
    try:
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id)
        text = " ".join(getattr(x, "text", str(x)) for x in transcript)
        return video_id, text[:100000]
    except Exception:
        return video_id or "", ""
