"""
ArixByte Music Bot - Audio Provider & Extraction Service
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    import discord
except ImportError:
    discord = None

from utils.errors import AudioProviderError, TrackNotFoundError

logger = logging.getLogger("ArixByteMusic.AudioProvider")


@dataclass
class Track:
    """Represents a playable musical track within ArixByte Music."""
    id: str
    title: str
    artist: str
    url: str
    duration: int  # in seconds
    thumbnail: Optional[str] = None
    stream_url: Optional[str] = None
    requester: Optional[Any] = None  # discord.Member or discord.User
    is_live: bool = False
    source: str = "youtube"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize track for MongoDB persistence."""
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "url": self.url,
            "duration": self.duration,
            "thumbnail": self.thumbnail,
            "requester_id": getattr(self.requester, "id", None),
            "requester_name": getattr(self.requester, "display_name", None),
            "is_live": self.is_live,
            "source": self.source,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], requester: Optional[Any] = None) -> Track:
        """Deserialize track from MongoDB document."""
        return cls(
            id=data.get("id", ""),
            title=data.get("title", "Unknown Title"),
            artist=data.get("artist", "Unknown Artist"),
            url=data.get("url", ""),
            duration=data.get("duration", 0),
            thumbnail=data.get("thumbnail"),
            requester=requester,
            is_live=data.get("is_live", False),
            source=data.get("source", "youtube"),
            created_at=data.get("created_at", time.time()),
        )


class BaseAudioProvider(ABC):
    """Abstract interface defining the audio extraction and recommendation protocol."""

    @abstractmethod
    async def search(self, query: str, requester: Any) -> List[Track]:
        """Search or resolve tracks from a URL or query string."""
        pass

    @abstractmethod
    async def get_stream_url(self, track: Track) -> str:
        """Resolve a direct, unexpired media stream URL for FFmpeg playback."""
        pass

    @abstractmethod
    async def get_recommendations(self, track: Track, history_urls: List[str]) -> List[Track]:
        """Provide intelligent autoplay recommendations based on track metadata."""
        pass


class YTDLPProvider(BaseAudioProvider):
    """
    Production-ready audio extractor utilizing yt-dlp.
    Complies with platform terms by querying public endpoints without DRM bypass.
    """

    # Optimized extraction options
    YTDL_OPTIONS: Dict[str, Any] = {
        "format": "bestaudio/best",
        "extract_flat": "in_playlist",
        "skip_download": True,
        "nocheckcertificate": True,
        "ignoreerrors": True,
        "logtostderr": False,
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch",
        "source_address": "0.0.0.0",  # Bind to IPv4
        "socket_timeout": 10,
        "geo_bypass": True,
    }

    # Strict stream resolving options (extract direct audio format)
    STREAM_OPTIONS: Dict[str, Any] = {
        "format": "bestaudio/best",
        "skip_download": True,
        "nocheckcertificate": True,
        "logtostderr": False,
        "quiet": True,
        "no_warnings": True,
        "geo_bypass": True,
        "noplaylist": True,
    }

    def __init__(self):
        if yt_dlp is None:
            logger.warning("yt-dlp is not installed in the current environment.")
        self._ytdl = yt_dlp.YoutubeDL(self.YTDL_OPTIONS) if yt_dlp else None
        self._stream_ytdl = yt_dlp.YoutubeDL(self.STREAM_OPTIONS) if yt_dlp else None

    async def search(self, query: str, requester: Any) -> List[Track]:
        """
        Search for queries or extract info from direct song/playlist URLs.
        Returns a list of extracted Track objects.
        """
        if self._ytdl is None:
            raise AudioProviderError("yt-dlp is unavailable in the environment.")

        loop = asyncio.get_running_loop()

        def _extract():
            # If query is not a direct URL, prepend default search
            target_query = query.strip()
            if not target_query.startswith(("http://", "https://")):
                target_query = f"ytsearch5:{target_query}"

            try:
                data = self._ytdl.extract_info(target_query, download=False)
                return data
            except Exception as e:
                logger.error("yt-dlp extraction error for query '%s': %s", query, e)
                return None

        data = await loop.run_in_executor(None, _extract)
        if not data:
            raise TrackNotFoundError(query)

        tracks: List[Track] = []

        # Case 1: Search results or playlist returned in 'entries'
        if "entries" in data:
            entries = data["entries"]
            if not entries:
                raise TrackNotFoundError(query)

            for entry in entries:
                if not entry:
                    continue
                tracks.append(self._parse_entry(entry, requester))
        else:
            # Case 2: Single track
            tracks.append(self._parse_entry(data, requester))

        if not tracks:
            raise TrackNotFoundError(query)

        return tracks

    def _parse_entry(self, entry: Dict[str, Any], requester: Any) -> Track:
        """Parse raw metadata entry into a Track instance."""
        track_id = entry.get("id", "")
        title = entry.get("title") or "Unknown Title"
        artist = entry.get("uploader") or entry.get("channel") or entry.get("artist") or "Unknown Artist"
        url = entry.get("webpage_url") or entry.get("url") or f"https://www.youtube.com/watch?v={track_id}"
        duration = int(entry.get("duration") or 0)
        
        # Resolve best thumbnail
        thumbnail = entry.get("thumbnail")
        if not thumbnail and entry.get("thumbnails"):
            thumbnail = entry["thumbnails"][-1].get("url")

        stream_url = entry.get("url") if entry.get("url", "").startswith("http") else None
        is_live = bool(entry.get("is_live", False))

        return Track(
            id=track_id,
            title=title,
            artist=artist,
            url=url,
            duration=duration,
            thumbnail=thumbnail,
            stream_url=stream_url,
            requester=requester,
            is_live=is_live,
            source="youtube"
        )

    async def get_stream_url(self, track: Track) -> str:
        """
        Extract fresh direct audio streaming URL.
        Handles URL expiration gracefully.
        """
        if self._stream_ytdl is None:
            raise AudioProviderError("yt-dlp is unavailable.")

        # If stream_url exists and looks like direct media link, test or re-extract
        loop = asyncio.get_running_loop()

        def _resolve():
            try:
                info = self._stream_ytdl.extract_info(track.url, download=False)
                if not info:
                    return None
                # If 'url' is provided in direct audio formats
                if "url" in info:
                    return info["url"]
                # Look inside formats
                formats = info.get("formats", [])
                audio_formats = [f for f in formats if f.get("acodec") != "none" and f.get("vcodec") == "none"]
                if audio_formats:
                    # Pick highest bitrate audio
                    audio_formats.sort(key=lambda f: f.get("abr") or 0, reverse=True)
                    return audio_formats[0].get("url")
                if formats:
                    return formats[-1].get("url")
                return None
            except Exception as e:
                logger.error("Failed to resolve stream URL for '%s': %s", track.title, e)
                return None

        resolved_url = await loop.run_in_executor(None, _resolve)
        if not resolved_url:
            raise AudioProviderError(f"Could not extract audio stream for: {track.title}")

        track.stream_url = resolved_url
        return resolved_url

    async def get_recommendations(self, track: Track, history_urls: List[str]) -> List[Track]:
        """
        Generate intelligent autoplay recommendations.
        Uses artist/genre searches, related recommendations, and filters past history.
        """
        if self._ytdl is None:
            return []

        loop = asyncio.get_running_loop()
        history_set = set(history_urls)

        # Strategy: Search related tracks using artist and track title keywords
        search_terms = [
            f"ytsearch8:{track.artist} similar music",
            f"ytsearch8:{track.artist} {track.title} mix",
            f"ytsearch8:{track.artist} top tracks"
        ]

        def _fetch_candidates():
            for query in search_terms:
                try:
                    data = self._ytdl.extract_info(query, download=False)
                    if data and "entries" in data and data["entries"]:
                        candidates = []
                        for entry in data["entries"]:
                            if not entry:
                                continue
                            t = self._parse_entry(entry, track.requester)
                            if t.url not in history_set and t.id != track.id:
                                candidates.append(t)
                        if candidates:
                            return candidates
                except Exception as ex:
                    logger.debug("Recommendation search '%s' failed: %s", query, ex)
            return []

        candidates = await loop.run_in_executor(None, _fetch_candidates)
        return candidates


def create_ffmpeg_source(
    stream_url: str,
    ffmpeg_path: str = "ffmpeg",
    volume: float = 1.0,
    seek_seconds: Optional[int] = None
) -> Any:
    """
    Constructs an optimized discord.FFmpegPCMAudio wrapped in PCMVolumeTransformer.
    Applies reconnect options for stream stability and optional seeking.
    """
    if discord is None:
        raise AudioProviderError("discord.py is not installed.")

    before_args = [
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
    ]

    if seek_seconds and seek_seconds > 0:
        before_args.extend(["-ss", str(seek_seconds)])

    ffmpeg_options = {
        "before_options": " ".join(before_args),
        "options": "-vn -loglevel error",
    }

    try:
        audio_source = discord.FFmpegPCMAudio(
            stream_url,
            executable=ffmpeg_path,
            **ffmpeg_options
        )
        return discord.PCMVolumeTransformer(audio_source, volume=volume)
    except Exception as e:
        logger.error("Failed to initialize FFmpeg audio source: %s", e)
        raise AudioProviderError(f"FFmpeg audio pipeline failure: {e}")
