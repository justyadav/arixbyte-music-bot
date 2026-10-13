"""
ArixByte Music Bot - Autoplay Management Cog
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations

import logging
from typing import Optional

try:
    import discord
    from discord import app_commands
    from discord.ext import commands
except ImportError:
    discord = None
    app_commands = None
    commands = None

from services.music_manager import MusicManager
from database.mongo import MongoManager
from utils.permissions import MusicPermissionChecker
from utils.embeds import ArixByteEmbeds

logger = logging.getLogger("ArixByteMusic.AutoplayCog")


class AutoplayCog(commands.Cog, name="Autoplay"):
    """Automatic related track recommendation and continuous playback control."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def music_manager(self) -> MusicManager:
        return self.bot.music_manager

    @property
    def db_manager(self) -> MongoManager:
        return self.bot.db_manager

    @app_commands.command(name="autoplay", description="Enable or disable automatic music recommendations when the queue ends.")
    @app_commands.describe(toggle="Explicitly set autoplay state or leave blank to toggle")
    @app_commands.choices(toggle=[
        app_commands.Choice(name="Enable Autoplay", value="on"),
        app_commands.Choice(name="Disable Autoplay", value="off"),
    ])
    async def autoplay(self, interaction: discord.Interaction, toggle: Optional[app_commands.Choice[str]] = None):
        await MusicPermissionChecker.require_playback_control(interaction, self.db_manager)
        player = self.music_manager.get_player(interaction.guild_id)

        if toggle:
            player.autoplay = (toggle.value == "on")
        else:
            player.autoplay = not player.autoplay

        state_str = "ENABLED" if player.autoplay else "DISABLED"
        emoji = "✨" if player.autoplay else "⏹️"

        embed = ArixByteEmbeds.success(
            "Autoplay Mode",
            f"{emoji} Continuous autoplay recommendations are now **{state_str}**.\n"
            f"*When your queue concludes, ArixByte Music will automatically find and queue matching tracks.*"
            if player.autoplay else
            f"{emoji} Autoplay is now **DISABLED**. Playback will stop when the current queue concludes."
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoplayCog(bot))
