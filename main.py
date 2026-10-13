"""
ArixByte Music Bot - Entry Point & Application Lifecycle
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import shutil
import sys
from typing import Optional

try:
    import discord
    from discord.ext import commands
    from discord import app_commands
except ImportError:
    discord = None
    commands = None
    app_commands = None

from config import config, BrandConfig
from database.mongo import MongoManager
from services.audio_provider import YTDLPProvider
from services.music_manager import MusicManager
from utils.embeds import ArixByteEmbeds
from utils.errors import (
    ArixByteMusicError,
    NotInVoiceChannelError,
    ChannelMismatchError,
    PermissionDeniedError,
    TrackNotFoundError,
    QueueEmptyError,
    PlaylistError
)

# Configure structured logging
logging.basicConfig(
    level=getattr(logging, config.log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ArixByteMusic.Main")


class ArixByteBot(commands.Bot):
    """Production Discord client for ArixByte Music."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.voice_states = True

        activity = discord.Activity(
            type=discord.ActivityType.listening,
            name=BrandConfig.ACTIVITY_NAME
        )

        super().__init__(
            command_prefix="!",  # Slash commands are primary; prefix used as fallback
            intents=intents,
            activity=activity,
            status=discord.Status.online,
            help_command=None
        )

        # Core services
        self.db_manager: MongoManager = MongoManager(
            uri=config.mongo_uri,
            db_name=config.mongo_db_name
        )
        self.audio_provider = YTDLPProvider()
        self.music_manager = MusicManager(
            bot=self,
            audio_provider=self.audio_provider,
            db_manager=self.db_manager
        )

    async def setup_hook(self) -> None:
        """Asynchronous initialization: database, cogs, and slash command registration."""
        logger.info("Initializing %s (Company: %s)...", BrandConfig.NAME, BrandConfig.COMPANY)

        # 1. Connect MongoDB
        db_connected = await self.db_manager.connect()
        if not db_connected:
            logger.warning("MongoDB failed to connect. Running in degraded memory-only mode for this session.")

        # 2. Check FFmpeg availability
        ffmpeg_location = shutil.which(config.ffmpeg_path)
        if ffmpeg_location:
            logger.info("Found FFmpeg binary at: %s", ffmpeg_location)
        else:
            logger.error("FFmpeg was not found in PATH or at '%s'. Audio playback will fail until FFmpeg is installed.", config.ffmpeg_path)

        # 3. Load Cogs
        cog_modules = [
            "cogs.playback",
            "cogs.queue",
            "cogs.autoplay",
            "cogs.playlists",
            "cogs.settings"
        ]

        for cog in cog_modules:
            try:
                await self.load_extension(cog)
                logger.info("Loaded extension: %s", cog)
            except Exception as e:
                logger.critical("Failed to load cog %s: %s", cog, e, exc_info=True)

        # 4. Synchronize slash commands
        try:
            if config.dev_guild_id:
                guild = discord.Object(id=config.dev_guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logger.info("Synced %d slash commands to Dev Guild ID: %d", len(synced), config.dev_guild_id)
            else:
                synced = await self.tree.sync()
                logger.info("Synced %d global slash commands across Discord.", len(synced))
        except Exception as e:
            logger.error("Failed to sync slash commands with Discord tree: %s", e)

    async def on_ready(self) -> None:
        """Executed when the bot successfully logs in and gateway shards connect."""
        logger.info("==================================================")
        logger.info("%s is online and ready!", BrandConfig.NAME)
        logger.info("Logged in as: %s (ID: %s)", self.user, self.user.id if self.user else "N/A")
        logger.info("Connected to %d guilds | Latency: %.2f ms", len(self.guilds), self.latency * 1000)
        logger.info("Tagline: %s", BrandConfig.TAGLINE)
        logger.info("==================================================")

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ) -> None:
        """
        Handle voice state changes for:
        1. Auto-disconnect when voice channel is empty.
        2. Clean shutdown when the bot itself is kicked or disconnected.
        """
        # If the bot itself was disconnected from a channel
        if member.id == self.user.id and before.channel and not after.channel:
            logger.info("Bot was disconnected from voice channel %s in guild %d", before.channel.name, before.channel.guild.id)
            player = self.music_manager.players.get(before.channel.guild.id)
            if player:
                await player.stop(clear_queue=True, disconnect=False)
                player.voice_client = None
            return

        # Check guilds where bot has an active voice connection
        guild = member.guild
        bot_voice = guild.voice_client

        if not bot_voice or not bot_voice.channel:
            return

        player = self.music_manager.get_player(guild.id)

        # Count non-bot members in the voice channel
        non_bot_members = [m for m in bot_voice.channel.members if not m.bot]

        if len(non_bot_members) == 0:
            # Voice channel is empty; start countdown if not already started
            if not player.empty_vc_task or player.empty_vc_task.done():
                player.start_empty_timer(reason=f"Voice channel '{bot_voice.channel.name}' has 0 listeners.")
        else:
            # Members present; cancel any pending disconnect timer
            player.cancel_empty_timer()

    async def close(self) -> None:
        """Gracefully release database and audio player resources on exit."""
        logger.info("Initiating graceful shutdown for %s...", BrandConfig.NAME)
        await self.music_manager.cleanup_all()
        await self.db_manager.close()
        await super().close()
        logger.info("ArixByte Music shutdown sequence complete.")


def handle_signals(bot: ArixByteBot, loop: asyncio.AbstractEventLoop) -> None:
    """Attach POSIX signal listeners for smooth Pterodactyl container termination."""
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.close()))
        except (NotImplementedError, RuntimeError):
            # Fallback for environments without add_signal_handler support (e.g. Windows)
            pass


async def main() -> None:
    """Application bootstrap."""
    try:
        config.validate()
    except ValueError as e:
        logger.critical("Configuration validation failed: %s", e)
        sys.exit(1)

    bot = ArixByteBot()

    # Global slash command error handler
    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ) -> None:
        # Unwrap underlying exceptions
        actual_error = getattr(error, "original", error)

        if isinstance(actual_error, app_commands.CommandOnCooldown):
            embed = ArixByteEmbeds.warning(
                "Command Cooldown",
                f"Please wait `{actual_error.retry_after:.1f}s` before using this command again."
            )
        elif isinstance(actual_error, NotInVoiceChannelError):
            embed = ArixByteEmbeds.warning("Voice Required", str(actual_error))
        elif isinstance(actual_error, ChannelMismatchError):
            embed = ArixByteEmbeds.warning("Channel Mismatch", str(actual_error))
        elif isinstance(actual_error, PermissionDeniedError):
            embed = ArixByteEmbeds.error("Permission Denied", str(actual_error))
        elif isinstance(actual_error, TrackNotFoundError):
            embed = ArixByteEmbeds.error("Track Not Found", str(actual_error))
        elif isinstance(actual_error, QueueEmptyError):
            embed = ArixByteEmbeds.warning("Queue Empty", str(actual_error))
        elif isinstance(actual_error, PlaylistError):
            embed = ArixByteEmbeds.error("Playlist Error", str(actual_error))
        else:
            logger.error("Unhandled slash command error in '%s': %s", interaction.command.name if interaction.command else "unknown", actual_error, exc_info=True)
            embed = ArixByteEmbeds.error(
                "Command Error",
                "An unexpected issue occurred while executing this request. Our team has logged the event."
            )

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as send_err:
            logger.error("Failed to send error response to interaction: %s", send_err)

    loop = asyncio.get_running_loop()
    handle_signals(bot, loop)

    try:
        async with bot:
            await bot.start(config.token)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot process exited.")
