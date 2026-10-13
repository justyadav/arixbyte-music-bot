"""
ArixByte Music Bot - Database Models
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


@dataclass
class GuildSettingsModel:
    """Guild configuration and DJ permission schema."""
    guild_id: int
    dj_role_id: Optional[int] = None
    dj_only_controls: bool = False
    default_volume: int = 100
    empty_vc_timeout: int = 180
    allow_server_playlists: bool = True
    autoplay_enabled: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GuildSettingsModel:
        return cls(
            guild_id=data["guild_id"],
            dj_role_id=data.get("dj_role_id"),
            dj_only_controls=data.get("dj_only_controls", False),
            default_volume=data.get("default_volume", 100),
            empty_vc_timeout=data.get("empty_vc_timeout", 180),
            allow_server_playlists=data.get("allow_server_playlists", True),
            autoplay_enabled=data.get("autoplay_enabled", False),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PlaylistTrackModel:
    """Serialized track item inside a stored playlist."""
    title: str
    artist: str
    url: str
    duration: int  # in seconds
    thumbnail: Optional[str] = None
    requester_name: Optional[str] = None
    requester_id: Optional[int] = None
    added_at: float = field(default_factory=time.time)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PlaylistTrackModel:
        return cls(
            title=data.get("title", "Unknown Title"),
            artist=data.get("artist", "Unknown Artist"),
            url=data.get("url", ""),
            duration=data.get("duration", 0),
            thumbnail=data.get("thumbnail"),
            requester_name=data.get("requester_name"),
            requester_id=data.get("requester_id"),
            added_at=data.get("added_at", time.time()),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PlaylistModel:
    """User or Server playlist schema."""
    name: str
    owner_id: int
    is_server_playlist: bool = False
    guild_id: Optional[int] = None
    tracks: List[PlaylistTrackModel] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def track_count(self) -> int:
        return len(self.tracks)

    @property
    def total_duration(self) -> int:
        return sum(t.duration for t in self.tracks)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PlaylistModel:
        raw_tracks = data.get("tracks", [])
        parsed_tracks = [
            PlaylistTrackModel.from_dict(t) if isinstance(t, dict) else t
            for t in raw_tracks
        ]
        return cls(
            name=data.get("name", "Untitled Playlist"),
            owner_id=data.get("owner_id", 0),
            is_server_playlist=data.get("is_server_playlist", False),
            guild_id=data.get("guild_id"),
            tracks=parsed_tracks,
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "name_lower": self.name.lower(),
            "owner_id": self.owner_id,
            "is_server_playlist": self.is_server_playlist,
            "guild_id": self.guild_id,
            "tracks": [t.to_dict() for t in self.tracks],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
