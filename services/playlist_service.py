"""
ArixByte Music Bot - Playlist Management Service
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Optional, List, Dict, Any

from config import config
from database.mongo import MongoManager
from database.models import PlaylistModel, PlaylistTrackModel
from services.audio_provider import Track
from utils.errors import (
    PlaylistNotFoundError,
    PlaylistLimitReachedError,
    ArixByteMusicError
)

logger = logging.getLogger("ArixByteMusic.PlaylistService")


class PlaylistService:
    """Business logic for creating, managing, and persisting playlists in MongoDB."""

    def __init__(self, db_manager: MongoManager):
        self.db: MongoManager = db_manager

    async def create_playlist(
        self,
        name: str,
        owner_id: int,
        guild_id: Optional[int] = None,
        is_server_playlist: bool = False
    ) -> PlaylistModel:
        """Create a new playlist."""
        name_clean = name.strip()
        if not name_clean:
            raise ArixByteMusicError("Playlist name cannot be empty.")

        existing = await self.db.get_playlist(
            name=name_clean,
            owner_id=owner_id,
            guild_id=guild_id,
            server_playlist=is_server_playlist
        )
        if existing:
            raise ArixByteMusicError(f"A playlist named `{name_clean}` already exists.")

        playlist = PlaylistModel(
            name=name_clean,
            owner_id=owner_id,
            is_server_playlist=is_server_playlist,
            guild_id=guild_id,
            tracks=[],
            created_at=time.time(),
            updated_at=time.time()
        )

        success = await self.db.save_playlist(playlist)
        if not success:
            raise ArixByteMusicError("Database error occurred while creating playlist.")

        return playlist

    async def get_playlist(
        self,
        name: str,
        owner_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        is_server_playlist: bool = False
    ) -> PlaylistModel:
        """Fetch playlist or raise PlaylistNotFoundError."""
        playlist = await self.db.get_playlist(
            name=name.strip(),
            owner_id=owner_id,
            guild_id=guild_id,
            server_playlist=is_server_playlist
        )
        if not playlist:
            raise PlaylistNotFoundError(name)
        return playlist

    async def add_track(
        self,
        name: str,
        track: Track,
        owner_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        is_server_playlist: bool = False
    ) -> PlaylistModel:
        """Append a track to a playlist."""
        playlist = await self.get_playlist(
            name=name,
            owner_id=owner_id,
            guild_id=guild_id,
            is_server_playlist=is_server_playlist
        )

        if len(playlist.tracks) >= config.max_playlist_tracks:
            raise PlaylistLimitReachedError(config.max_playlist_tracks)

        track_model = PlaylistTrackModel(
            title=track.title,
            artist=track.artist,
            url=track.url,
            duration=track.duration,
            thumbnail=track.thumbnail,
            requester_name=getattr(track.requester, "display_name", "User"),
            requester_id=getattr(track.requester, "id", None)
        )

        playlist.tracks.append(track_model)
        playlist.updated_at = time.time()

        await self.db.save_playlist(playlist)
        return playlist

    async def remove_track(
        self,
        name: str,
        index: int,
        owner_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        is_server_playlist: bool = False
    ) -> tuple[PlaylistModel, PlaylistTrackModel]:
        """Remove a track at a specific 1-based index."""
        playlist = await self.get_playlist(
            name=name,
            owner_id=owner_id,
            guild_id=guild_id,
            is_server_playlist=is_server_playlist
        )

        if index < 1 or index > len(playlist.tracks):
            raise ArixByteMusicError(f"Track index #{index} is invalid for playlist `{name}` (contains {len(playlist.tracks)} tracks).")

        removed = playlist.tracks.pop(index - 1)
        playlist.updated_at = time.time()

        await self.db.save_playlist(playlist)
        return playlist, removed

    async def shuffle_playlist(
        self,
        name: str,
        owner_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        is_server_playlist: bool = False
    ) -> PlaylistModel:
        """Shuffle tracks in place within a playlist."""
        playlist = await self.get_playlist(
            name=name,
            owner_id=owner_id,
            guild_id=guild_id,
            is_server_playlist=is_server_playlist
        )

        if len(playlist.tracks) < 2:
            raise ArixByteMusicError("Playlist requires at least 2 tracks to shuffle.")

        random.shuffle(playlist.tracks)
        playlist.updated_at = time.time()
        await self.db.save_playlist(playlist)
        return playlist

    async def delete_playlist(
        self,
        name: str,
        owner_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        is_server_playlist: bool = False
    ) -> bool:
        """Delete a playlist."""
        return await self.db.delete_playlist(
            name=name.strip(),
            owner_id=owner_id,
            guild_id=guild_id,
            server_playlist=is_server_playlist
        )

    async def list_user_playlists(self, owner_id: int) -> List[PlaylistModel]:
        """Retrieve user playlists."""
        return await self.db.list_user_playlists(owner_id)

    async def list_server_playlists(self, guild_id: int) -> List[PlaylistModel]:
        """Retrieve server playlists."""
        return await self.db.list_server_playlists(guild_id)
