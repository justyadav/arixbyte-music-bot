"""
ArixByte Music Bot - Queue Management Cog
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

try:
    import discord
    from discord import app_commands
    from discord.ext import commands
    from discord.ui import View, Button
except ImportError:
    discord = None
    app_commands = None
    commands = None
    View = object
    Button = object

from config import BrandConfig
from services.music_manager import MusicManager, LoopMode, GuildPlayer
from database.mongo import MongoManager
from utils.permissions import MusicPermissionChecker
from utils.embeds import ArixByteEmbeds

logger = logging.getLogger("ArixByteMusic.QueueCog")


class QueuePaginationView(View):
    """Interactive paginated view for browsing large queues."""

    def __init__(self, player: GuildPlayer, current_page: int = 1, page_size: int = 10):
        super().__init__(timeout=120)
        self.player = player
        self.current_page = current_page
        self.page_size = page_size
        self._update_buttons()

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(len(self.player.queue) / self.page_size))

    def _update_buttons(self) -> None:
        self.clear_items()

        # Prev button
        prev_btn = Button(
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            disabled=self.current_page <= 1
        )
        prev_btn.callback = self._prev_page
        self.add_item(prev_btn)

        # Indicator button (disabled)
        ind_btn = Button(
            label=f"Page {self.current_page} / {self.total_pages}",
            style=discord.ButtonStyle.primary,
            disabled=True
        )
        self.add_item(ind_btn)

        # Next button
        next_btn = Button(
            emoji="➡️",
            style=discord.ButtonStyle.secondary,
            disabled=self.current_page >= self.total_pages
        )
        next_btn.callback = self._next_page
        self.add_item(next_btn)

    async def _render_embed(self) -> discord.Embed:
        return ArixByteEmbeds.queue_embed(
            current_track=self.player.current_track,
            queue_tracks=list(self.player.queue),
            page=self.current_page,
            page_size=self.page_size,
            loop_mode=self.player.loop_mode,
            autoplay=self.player.autoplay
        )

    async def _prev_page(self, interaction: discord.Interaction):
        if self.current_page > 1:
            self.current_page -= 1
        self._update_buttons()
        embed = await self._render_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _next_page(self, interaction: discord.Interaction):
        if self.current_page < self.total_pages:
            self.current_page += 1
        self._update_buttons()
        embed = await self._render_embed()
        await interaction.response.edit_message(embed=embed, view=self)


class QueueCog(commands.Cog, name="Queue"):
    """Queue inspection, looping, and reorganization commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def music_manager(self) -> MusicManager:
        return self.bot.music_manager

    @property
    def db_manager(self) -> MongoManager:
        return self.bot.db_manager

    # -------------------------------------------------------------------------
    # /queue
    # -------------------------------------------------------------------------
    @app_commands.command(name="queue", description="View upcoming tracks in the music queue.")
    @app_commands.describe(page="Queue page number (defaults to 1)")
    async def queue(self, interaction: discord.Interaction, page: Optional[int] = 1):
        player = self.music_manager.get_player(interaction.guild_id)

        target_page = max(1, page or 1)
        embed = ArixByteEmbeds.queue_embed(
            current_track=player.current_track,
            queue_tracks=list(player.queue),
            page=target_page,
            page_size=10,
            loop_mode=player.loop_mode,
            autoplay=player.autoplay
        )

        view = QueuePaginationView(player=player, current_page=target_page, page_size=10)
        await interaction.response.send_message(embed=embed, view=view)

    # -------------------------------------------------------------------------
    # /shuffle
    # -------------------------------------------------------------------------
    @app_commands.command(name="shuffle", description="Randomize the order of queued tracks.")
    async def shuffle(self, interaction: discord.Interaction):
        await MusicPermissionChecker.require_playback_control(interaction, self.db_manager)
        player = self.music_manager.get_player(interaction.guild_id)

        if len(player.queue) < 2:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("Cannot Shuffle", "The queue must contain at least 2 tracks to shuffle."),
                ephemeral=True
            )
            return

        count = player.shuffle()
        await interaction.response.send_message(
            embed=ArixByteEmbeds.success(
                "Queue Shuffled",
                f"🔀 Successfully shuffled **{count}** tracks in the queue."
            )
        )

    # -------------------------------------------------------------------------
    # /loop
    # -------------------------------------------------------------------------
    @app_commands.command(name="loop", description="Configure loop mode for the current song or entire queue.")
    @app_commands.describe(mode="Choose loop mode")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Off (Disable looping)", value="off"),
        app_commands.Choice(name="Song (Loop current track)", value="song"),
        app_commands.Choice(name="Queue (Loop entire queue)", value="queue"),
    ])
    async def loop(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        await MusicPermissionChecker.require_playback_control(interaction, self.db_manager)
        player = self.music_manager.get_player(interaction.guild_id)

        player.loop_mode = mode.value
        await interaction.response.send_message(
            embed=ArixByteEmbeds.success(
                "Loop Mode Updated",
                f"🔁 Playback loop mode is now set to: **{mode.name}**"
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(QueueCog(bot))
