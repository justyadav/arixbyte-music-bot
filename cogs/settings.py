"""
ArixByte Music Bot - Utility, Settings & Diagnostic Cog
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations

import logging
import platform
import sys
import time
from typing import Optional

try:
    import discord
    from discord import app_commands
    from discord.ext import commands
except ImportError:
    discord = None
    app_commands = None
    commands = None

from config import BrandConfig, config
from services.music_manager import MusicManager
from database.mongo import MongoManager
from database.models import GuildSettingsModel
from utils.embeds import ArixByteEmbeds, format_duration
from utils.permissions import MusicPermissionChecker

logger = logging.getLogger("ArixByteMusic.SettingsCog")


class SettingsCog(commands.GroupCog, name="music"):
    """Server configuration, system status, and help documentation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time: float = time.time()

    @property
    def music_manager(self) -> MusicManager:
        return self.bot.music_manager

    @property
    def db_manager(self) -> MongoManager:
        return self.bot.db_manager

    # -------------------------------------------------------------------------
    # /music help
    # -------------------------------------------------------------------------
    @app_commands.command(name="help", description="Explore ArixByte Music commands, features, and controls.")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"{BrandConfig.NAME} — Command Handbook",
            description=f"Welcome to **{BrandConfig.NAME}**, engineered by **{BrandConfig.COMPANY}**.\n"
                        f"*{BrandConfig.TAGLINE}*\n\n"
                        f"Below is a complete reference of slash commands and interactive features.",
            color=BrandConfig.COLOR_PRIMARY
        )

        embed.add_field(
            name="🎵 Playback Commands",
            value="• `/play <query>` — Search or play a direct audio/playlist link\n"
                  "• `/pause` & `/resume` — Pause or resume the stream\n"
                  "• `/skip` — Advance to the next song\n"
                  "• `/previous` — Replay previous track from history\n"
                  "• `/stop` — Terminate playback and clear queue\n"
                  "• `/nowplaying` — Live track card with progress indicator\n"
                  "• `/volume <level>` — Adjust volume (1-200%)\n"
                  "• `/seek <time>` — Jump to timestamp (e.g. `1:30` or `90`)\n"
                  "• `/join` & `/leave` — Manage bot voice connection\n"
                  "• `/lyrics [query]` — View song lyrics via verified provider",
            inline=False
        )

        embed.add_field(
            name="📑 Queue & Autoplay",
            value="• `/queue [page]` — View paginated track queue with navigation\n"
                  "• `/shuffle` — Randomize upcoming queue order\n"
                  "• `/loop <off|song|queue>` — Toggle track or queue repetition\n"
                  "• `/autoplay [toggle]` — Continuous smart music recommendations",
            inline=False
        )

        embed.add_field(
            name="📃 Persistent Playlists",
            value="• `/playlist create <name>` — Create personal or server playlist\n"
                  "• `/playlist add <name> <query>` — Add song to playlist\n"
                  "• `/playlist remove <name> <index>` — Remove track by number\n"
                  "• `/playlist view <name>` — Paginated inspection of stored tracks\n"
                  "• `/playlist play <name>` — Enqueue all playlist songs\n"
                  "• `/playlist list` — View all your saved playlists\n"
                  "• `/playlist import <name> <url>` — Import YouTube/SoundCloud playlist\n"
                  "• `/playlist shuffle <name>` — Shuffle tracks inside playlist",
            inline=False
        )

        embed.add_field(
            name="⚙️ Administration & Status",
            value="• `/music settings` — Configure DJ roles, timeouts, and volume\n"
                  "• `/music status` — Diagnostic report, latency, node health\n"
                  "• `/music help` — Open this guide",
            inline=False
        )

        embed.add_field(
            name="🎮 Interactive Music Player",
            value="When music plays, an interactive embed appears with dual-row buttons:\n"
                  "• **Row 1:** ⏮️ Previous | ⏸️/▶️ Pause-Resume | ⏭️ Skip | ⏹️ Stop\n"
                  "• **Row 2:** 📃 Add to Playlist | 🔀 Shuffle | 🔁 Loop Mode | ✨ Autoplay | 🔊 Volume",
            inline=False
        )

        ArixByteEmbeds._apply_branding(embed)
        await interaction.response.send_message(embed=embed)

    # -------------------------------------------------------------------------
    # /music status
    # -------------------------------------------------------------------------
    @app_commands.command(name="status", description="Inspect ArixByte Music latency, memory, database, and audio node.")
    async def status(self, interaction: discord.Interaction):
        uptime_sec = time.time() - self.start_time
        latency_ms = round(self.bot.latency * 1000, 2)
        total_guilds = len(self.bot.guilds)
        active_players = sum(1 for p in self.music_manager.players.values() if p.is_playing or p.is_paused)
        voice_conns = len(self.bot.voice_clients)

        # Database latency check
        db_status = "Disconnected ❌"
        db_ping_str = "N/A"
        if self.db_manager.is_connected and self.db_manager.client:
            try:
                t0 = time.time()
                await self.db_manager.client.admin.command("ping")
                db_ping = round((time.time() - t0) * 1000, 2)
                db_status = "Connected ✅"
                db_ping_str = f"{db_ping} ms"
            except Exception:
                db_status = "Degraded ⚠️"

        embed = discord.Embed(
            title=f"⚡ {BrandConfig.NAME} — System Diagnostics",
            color=BrandConfig.COLOR_SECONDARY
        )

        embed.add_field(name="Bot Uptime", value=f"`{format_duration(uptime_sec)}`", inline=True)
        embed.add_field(name="Discord Gateway Ping", value=f"`{latency_ms} ms`", inline=True)
        embed.add_field(name="Servers (Guilds)", value=f"`{total_guilds}`", inline=True)

        embed.add_field(name="Active Music Streams", value=f"`{active_players}`", inline=True)
        embed.add_field(name="Voice Connections", value=f"`{voice_conns}`", inline=True)
        embed.add_field(name="Audio Provider", value=f"`{config.audio_provider.upper()}` (Modular)", inline=True)

        embed.add_field(name="MongoDB Status", value=f"`{db_status}`", inline=True)
        embed.add_field(name="Database Ping", value=f"`{db_ping_str}`", inline=True)
        embed.add_field(name="Runtime Environment", value=f"`Python {platform.python_version()}`", inline=True)

        ArixByteEmbeds._apply_branding(embed)
        await interaction.response.send_message(embed=embed)

    # -------------------------------------------------------------------------
    # /music settings
    # -------------------------------------------------------------------------
    @app_commands.command(name="settings", description="View or modify guild music settings and DJ roles.")
    @app_commands.describe(
        dj_role="Assign a DJ role for music control",
        dj_only_controls="Require DJ role to control playback",
        default_volume="Default volume for new sessions (1-200%)",
        empty_timeout="Inactivity seconds before disconnecting from empty voice (30-600s)"
    )
    async def settings(
        self,
        interaction: discord.Interaction,
        dj_role: Optional[discord.Role] = None,
        dj_only_controls: Optional[bool] = None,
        default_volume: Optional[int] = None,
        empty_timeout: Optional[int] = None
    ):
        settings: GuildSettingsModel = await self.db_manager.get_guild_settings(interaction.guild_id)

        # Check if user wants to update settings
        is_modifying = any(x is not None for x in [dj_role, dj_only_controls, default_volume, empty_timeout])

        if is_modifying:
            if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message(
                    embed=ArixByteEmbeds.error("Permission Denied", "Only administrators can configure music settings."),
                    ephemeral=True
                )
                return

            if dj_role is not None:
                settings.dj_role_id = dj_role.id
            if dj_only_controls is not None:
                settings.dj_only_controls = dj_only_controls
            if default_volume is not None:
                settings.default_volume = max(1, min(config.max_volume, default_volume))
            if empty_timeout is not None:
                settings.empty_vc_timeout = max(30, min(600, empty_timeout))

            await self.db_manager.save_guild_settings(settings)

            # Update live player
            player = self.music_manager.get_player(interaction.guild_id)
            player.empty_timeout = settings.empty_vc_timeout

            embed = ArixByteEmbeds.success(
                "Settings Updated",
                "Guild music preferences have been updated and saved to MongoDB."
            )
        else:
            embed = discord.Embed(
                title=f"⚙️ {BrandConfig.NAME} — Server Settings",
                description="Current music configuration for this Discord server:",
                color=BrandConfig.COLOR_PRIMARY
            )

        # Render current values
        dj_role_mention = f"<@&{settings.dj_role_id}>" if settings.dj_role_id else "*None (All members have control)*"
        embed.add_field(name="DJ Role", value=dj_role_mention, inline=True)
        embed.add_field(name="Strict DJ Mode", value=f"`{'Enabled' if settings.dj_only_controls else 'Disabled'}`", inline=True)
        embed.add_field(name="Default Volume", value=f"`{settings.default_volume}%`", inline=True)
        embed.add_field(name="Empty VC Timeout", value=f"`{settings.empty_vc_timeout} seconds`", inline=True)

        ArixByteEmbeds._apply_branding(embed)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(SettingsCog(bot))
