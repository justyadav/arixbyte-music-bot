"""
ArixByte Music Bot - Configuration Module
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations

import os
import sys
import logging
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()


class BrandConfig:
    """Branding constants and visual theme for ArixByte Music."""
    NAME: str = "ArixByte Music"
    COMPANY: str = "ArixByte Ltd."
    TAGLINE: str = "Your Music. Your Community."
    ACTIVITY_NAME: str = "music across Discord | /music help"
    WEBSITE_URL: str = "https://arixbyte.com"
    SUPPORT_URL: str = "https://discord.gg/arixbyte"
    
    # Modern dark theme with blue / purple accents
    COLOR_PRIMARY: int = 0x5865F2    # Discord Blurple / Electric Accent
    COLOR_SECONDARY: int = 0x7B2CBF  # Deep Purple / Royal Indigo
    COLOR_ACCENT: int = 0x6C5CE7     # Neon Lavender Accent
    COLOR_SUCCESS: int = 0x2ECC71    # Emerald Green
    COLOR_WARNING: int = 0xF1C40F    # Amber Yellow
    COLOR_ERROR: int = 0xE74C3C      # Crimson Red
    COLOR_DARK: int = 0x1E1F29       # Sleek Dark Slate

    # Icons & Emojis
    ICON_LOGO: str = "https://cdn.discordapp.com/embed/avatars/0.png"  # Default fallback or ArixByte CDN
    EMOJI_MUSIC: str = "🎵"
    EMOJI_PLAY: str = "▶️"
    EMOJI_PAUSE: str = "⏸️"
    EMOJI_PREVIOUS: str = "⏮️"
    EMOJI_SKIP: str = "⏭️"
    EMOJI_STOP: str = "⏹️"
    EMOJI_LOOP: str = "🔁"
    EMOJI_SHUFFLE: str = "🔀"
    EMOJI_PLAYLIST: str = "📃"
    EMOJI_VOLUME: str = "🔊"
    EMOJI_AUTOPLAY: str = "✨"
    EMOJI_SUCCESS: str = "✅"
    EMOJI_WARNING: str = "⚠️"
    EMOJI_ERROR: str = "❌"


@dataclass
class BotConfig:
    """Strongly typed application configuration parsed from environment variables."""
    # Discord credentials
    token: str = field(default_factory=lambda: os.getenv("DISCORD_TOKEN", ""))
    client_id: Optional[str] = field(default_factory=lambda: os.getenv("DISCORD_CLIENT_ID"))
    dev_guild_id: Optional[int] = field(
        default_factory=lambda: int(os.getenv("DEV_GUILD_ID")) if os.getenv("DEV_GUILD_ID") else None
    )

    # Database
    mongo_uri: str = field(
        default_factory=lambda: os.getenv("MONGO_URI", "mongodb://localhost:27017")
    )
    mongo_db_name: str = field(
        default_factory=lambda: os.getenv("MONGO_DB_NAME", "arixbyte_music")
    )

    # Audio playback configuration
    audio_provider: str = field(
        default_factory=lambda: os.getenv("AUDIO_PROVIDER", "ytdlp").lower()
    )
    ffmpeg_path: str = field(
        default_factory=lambda: os.getenv("FFMPEG_PATH", "ffmpeg")
    )

    # Playback constraints & defaults
    default_volume: int = field(
        default_factory=lambda: int(os.getenv("DEFAULT_VOLUME", "100"))
    )
    max_volume: int = field(
        default_factory=lambda: int(os.getenv("MAX_VOLUME", "200"))
    )
    empty_vc_timeout: int = field(
        default_factory=lambda: int(os.getenv("EMPTY_VC_TIMEOUT", "180"))
    )
    max_playlist_tracks: int = field(
        default_factory=lambda: int(os.getenv("MAX_PLAYLIST_TRACKS", "250"))
    )
    max_queue_length: int = field(
        default_factory=lambda: int(os.getenv("MAX_QUEUE_LENGTH", "1000"))
    )

    # External APIs
    genius_api_token: Optional[str] = field(
        default_factory=lambda: os.getenv("GENIUS_API_TOKEN") or None
    )

    # Diagnostics
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper()
    )

    def validate(self) -> None:
        """Validate required configuration at startup."""
        logger = logging.getLogger("ArixByteMusic.Config")
        if not self.token:
            logger.critical("DISCORD_TOKEN is missing! Provide it via environment variables or .env.")
            raise ValueError("DISCORD_TOKEN environment variable is required.")

        if not self.mongo_uri:
            logger.critical("MONGO_URI is missing! Provide a valid MongoDB connection string.")
            raise ValueError("MONGO_URI environment variable is required.")

        if self.default_volume < 1 or self.default_volume > self.max_volume:
            logger.warning("DEFAULT_VOLUME out of bounds (1-%d). Resetting to 100.", self.max_volume)
            self.default_volume = 100


# Singleton global config instance
config = BotConfig()
