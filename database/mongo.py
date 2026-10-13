"""
ArixByte Music Bot - MongoDB Connection & Operations Manager
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations

import logging
import asyncio
from typing import Optional, Dict, Any, List
import time

try:
    from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
    import pymongo
except ImportError:
    AsyncIOMotorClient = None
    AsyncIOMotorDatabase = None
    pymongo = None

from database.models import GuildSettingsModel, PlaylistModel, PlaylistTrackModel

logger = logging.getLogger("ArixByteMusic.Database")


class MongoManager:
    """Handles asynchronous MongoDB operations using Motor."""

    def __init__(self, uri: str, db_name: str = "arixbyte_music"):
        self.uri = uri
        self.db_name = db_name
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None
        self._connected: bool = False
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._connected and self.client is not None

    async def connect(self) -> bool:
        """Establish connection to MongoDB and ensure indexes."""
        if AsyncIOMotorClient is None:
            logger.error("Motor is not installed! MongoDB persistence will be unavailable.")
            self._connected = False
            return False

        async with self._lock:
            try:
                logger.info("Connecting to MongoDB at: %s ...", self.uri.split("@")[-1] if "@" in self.uri else self.uri)
                self.client = AsyncIOMotorClient(
                    self.uri,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                )
                self.db = self.client[self.db_name]
                
                # Test connection using admin ping
                await self.client.admin.command("ping")
                self._connected = True
                logger.info("Successfully connected to MongoDB database: %s", self.db_name)
                
                await self._ensure_indexes()
                return True
            except Exception as e:
                self._connected = False
                logger.error("Failed to connect to MongoDB: %s. Check MONGO_URI in .env.", e)
                return False

    async def _ensure_indexes(self) -> None:
        """Ensure optimal indexes on all collections for performance and uniqueness."""
        if not self.is_connected or self.db is None:
            return

        try:
            # Guild settings index
            await self.db.guild_settings.create_index("guild_id", unique=True)

            # Playlist indexes
            await self.db.playlists.create_index(
                [("owner_id", 1), ("name_lower", 1)],
                background=True
            )
            await self.db.playlists.create_index(
                [("guild_id", 1), ("name_lower", 1)],
                background=True
            )
            await self.db.playlists.create_index(
                [("is_server_playlist", 1), ("guild_id", 1)],
                background=True
            )

            # History index (with TTL of 30 days)
            await self.db.history.create_index(
                [("played_at", 1)],
                expireAfterSeconds=2592000,  # 30 days
                background=True
            )
            logger.debug("Database indexes verified successfully.")
        except Exception as e:
            logger.warning("Could not create database indexes: %s", e)

    async def close(self) -> None:
        """Gracefully close the MongoDB client connection."""
        if self.client:
            self.client.close()
            self._connected = False
            logger.info("MongoDB connection closed.")

    # -------------------------------------------------------------------------
    # Guild Settings Methods
    # -------------------------------------------------------------------------

    async def get_guild_settings(self, guild_id: int) -> GuildSettingsModel:
        """Fetch settings for a guild, or return default settings if none exist."""
        if not self.is_connected or self.db is None:
            return GuildSettingsModel(guild_id=guild_id)

        try:
            doc = await self.db.guild_settings.find_one({"guild_id": guild_id})
            if doc:
                return GuildSettingsModel.from_dict(doc)
            
            # Default settings
            settings = GuildSettingsModel(guild_id=guild_id)
            await self.save_guild_settings(settings)
            return settings
        except Exception as e:
            logger.error("Error retrieving guild settings for %d: %s", guild_id, e)
            return GuildSettingsModel(guild_id=guild_id)

    async def save_guild_settings(self, settings: GuildSettingsModel) -> bool:
        """Persist or update guild settings."""
        if not self.is_connected or self.db is None:
            return False

        try:
            settings.updated_at = time.time()
            data = settings.to_dict()
            await self.db.guild_settings.update_one(
                {"guild_id": settings.guild_id},
                {"$set": data},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error("Error saving guild settings for %d: %s", settings.guild_id, e)
            return False

    # -------------------------------------------------------------------------
    # Playlist Operations
    # -------------------------------------------------------------------------

    async def get_playlist(
        self,
        name: str,
        owner_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        server_playlist: bool = False
    ) -> Optional[PlaylistModel]:
        """Find a playlist by name for either a user or a server."""
        if not self.is_connected or self.db is None:
            return None

        query: Dict[str, Any] = {"name_lower": name.lower(), "is_server_playlist": server_playlist}
        if server_playlist:
            if guild_id is None:
                return None
            query["guild_id"] = guild_id
        else:
            if owner_id is None:
                return None
            query["owner_id"] = owner_id

        try:
            doc = await self.db.playlists.find_one(query)
            if doc:
                return PlaylistModel.from_dict(doc)
            return None
        except Exception as e:
            logger.error("Error fetching playlist '%s': %s", name, e)
            return None

    async def save_playlist(self, playlist: PlaylistModel) -> bool:
        """Insert or update a playlist document."""
        if not self.is_connected or self.db is None:
            return False

        try:
            playlist.updated_at = time.time()
            data = playlist.to_dict()
            filter_query: Dict[str, Any] = {
                "name_lower": playlist.name.lower(),
                "is_server_playlist": playlist.is_server_playlist,
            }
            if playlist.is_server_playlist:
                filter_query["guild_id"] = playlist.guild_id
            else:
                filter_query["owner_id"] = playlist.owner_id

            await self.db.playlists.update_one(
                filter_query,
                {"$set": data},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error("Error saving playlist '%s': %s", playlist.name, e)
            return False

    async def delete_playlist(
        self,
        name: str,
        owner_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        server_playlist: bool = False
    ) -> bool:
        """Remove a playlist document."""
        if not self.is_connected or self.db is None:
            return False

        query: Dict[str, Any] = {"name_lower": name.lower(), "is_server_playlist": server_playlist}
        if server_playlist:
            query["guild_id"] = guild_id
        else:
            query["owner_id"] = owner_id

        try:
            res = await self.db.playlists.delete_one(query)
            return res.deleted_count > 0
        except Exception as e:
            logger.error("Error deleting playlist '%s': %s", name, e)
            return False

    async def list_user_playlists(self, owner_id: int) -> List[PlaylistModel]:
        """Fetch all personal playlists owned by a user."""
        if not self.is_connected or self.db is None:
            return []

        try:
            cursor = self.db.playlists.find({"owner_id": owner_id, "is_server_playlist": False})
            playlists = []
            async for doc in cursor:
                playlists.append(PlaylistModel.from_dict(doc))
            return playlists
        except Exception as e:
            logger.error("Error listing user playlists for %d: %s", owner_id, e)
            return []

    async def list_server_playlists(self, guild_id: int) -> List[PlaylistModel]:
        """Fetch all server playlists for a guild."""
        if not self.is_connected or self.db is None:
            return []

        try:
            cursor = self.db.playlists.find({"guild_id": guild_id, "is_server_playlist": True})
            playlists = []
            async for doc in cursor:
                playlists.append(PlaylistModel.from_dict(doc))
            return playlists
        except Exception as e:
            logger.error("Error listing server playlists for guild %d: %s", guild_id, e)
            return []
