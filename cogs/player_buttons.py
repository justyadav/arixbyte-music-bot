"""
ArixByte Music Bot - Interactive Music Player UI Components
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING, Any

try:
    import discord
    from discord.ui import View, Button, Modal, TextInput, Select
except ImportError:
    discord = None
    View = object
    Button = object
    Modal = object
    TextInput = object
    Select = object

from config import BrandConfig, config
from utils.permissions import MusicPermissionChecker
from utils.embeds import ArixByteEmbeds
from utils.errors import ChannelMismatchError, NotInVoiceChannelError

if TYPE_CHECKING:
    from services.music_manager import GuildPlayer

logger = logging.getLogger("ArixByteMusic.PlayerButtons")


class VolumeSelectView(View):
    """Ephemeral view offering discrete volume presets and custom adjustment."""

    def __init__(self, player: GuildPlayer):
        super().__init__(timeout=60)
        self.player = player

        presets = [25, 50, 75, 100, 125, 150]
        for preset in presets:
            btn = Button(
                label=f"{preset}%",
                style=discord.ButtonStyle.primary if preset == player.volume else discord.ButtonStyle.secondary,
                custom_id=f"vol_preset_{preset}"
            )
            btn.callback = self._make_preset_callback(preset)
            self.add_item(btn)

    def _make_preset_callback(self, preset: int):
        async def _callback(interaction: discord.Interaction):
            await self.player.set_volume(preset)
            await interaction.response.send_message(
                embed=ArixByteEmbeds.success("Volume Adjusted", f"Playback volume set to **{preset}%**."),
                ephemeral=True
            )
        return _callback


class AddToPlaylistSelect(Select):
    """Dynamic select menu displaying user playlists for adding the current song."""

    def __init__(self, player: GuildPlayer, playlists: list):
        self.player = player
        options = [
            discord.SelectOption(
                label=p.name,
                description=f"{len(p.tracks)} tracks • {'Server Playlist' if p.is_server_playlist else 'Personal'}",
                emoji=BrandConfig.EMOJI_PLAYLIST,
                value=f"{p.name}:{'1' if p.is_server_playlist else '0'}"
            )
            for p in playlists[:25]
        ]
        super().__init__(placeholder="Select a playlist to store this song...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if not self.player.current_track:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("No Track", "No track is currently playing to add."),
                ephemeral=True
            )
            return

        name, is_server_str = self.values[0].split(":")
        is_server = is_server_str == "1"

        from services.playlist_service import PlaylistService
        service = PlaylistService(self.player.db_manager)

        try:
            guild_id = interaction.guild_id if is_server else None
            owner_id = interaction.user.id if not is_server else None

            await service.add_track(
                name=name,
                track=self.player.current_track,
                owner_id=owner_id,
                guild_id=guild_id,
                is_server_playlist=is_server
            )
            await interaction.response.send_message(
                embed=ArixByteEmbeds.success(
                    "Track Saved to Playlist",
                    f"Saved **{self.player.current_track.title}** into playlist **{name}**!"
                ),
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.error("Playlist Error", str(e)),
                ephemeral=True
            )


class AddToPlaylistView(View):
    """Ephemeral container view for playlist selection."""

    def __init__(self, player: GuildPlayer, playlists: list):
        super().__init__(timeout=60)
        self.add_item(AddToPlaylistSelect(player, playlists))


class PlayerControlView(View):
    """
    Two-row interactive Discord UI view attached to the active player embed.
    Row 1: Previous, Pause/Resume, Skip, Stop
    Row 2: Playlist, Shuffle, Loop, Autoplay, Volume
    """

    def __init__(self, player: GuildPlayer):
        super().__init__(timeout=None)
        self.player = player
        self._setup_buttons()

    def _setup_buttons(self) -> None:
        """Dynamically construct buttons based on player state."""
        self.clear_items()

        # ================= ROW 1: CORE CONTROLS =================
        # Previous
        prev_btn = Button(
            emoji=BrandConfig.EMOJI_PREVIOUS,
            style=discord.ButtonStyle.secondary,
            disabled=len(self.player.history) == 0,
            row=0,
            custom_id="arix_btn_prev"
        )
        prev_btn.callback = self._prev_callback
        self.add_item(prev_btn)

        # Pause / Resume
        if self.player.is_paused:
            pause_btn = Button(
                emoji=BrandConfig.EMOJI_PLAY,
                label="Resume",
                style=discord.ButtonStyle.success,
                row=0,
                custom_id="arix_btn_pause_resume"
            )
        else:
            pause_btn = Button(
                emoji=BrandConfig.EMOJI_PAUSE,
                label="Pause",
                style=discord.ButtonStyle.secondary,
                row=0,
                custom_id="arix_btn_pause_resume"
            )
        pause_btn.callback = self._pause_resume_callback
        self.add_item(pause_btn)

        # Skip
        skip_btn = Button(
            emoji=BrandConfig.EMOJI_SKIP,
            label="Skip",
            style=discord.ButtonStyle.primary,
            row=0,
            custom_id="arix_btn_skip"
        )
        skip_btn.callback = self._skip_callback
        self.add_item(skip_btn)

        # Stop
        stop_btn = Button(
            emoji=BrandConfig.EMOJI_STOP,
            label="Stop",
            style=discord.ButtonStyle.danger,
            row=0,
            custom_id="arix_btn_stop"
        )
        stop_btn.callback = self._stop_callback
        self.add_item(stop_btn)

        # ================= ROW 2: ADVANCED CONTROLS =================
        # Playlist (Add song)
        playlist_btn = Button(
            emoji=BrandConfig.EMOJI_PLAYLIST,
            label="Playlist",
            style=discord.ButtonStyle.secondary,
            row=1,
            custom_id="arix_btn_playlist"
        )
        playlist_btn.callback = self._playlist_callback
        self.add_item(playlist_btn)

        # Shuffle
        shuffle_btn = Button(
            emoji=BrandConfig.EMOJI_SHUFFLE,
            style=discord.ButtonStyle.secondary,
            row=1,
            custom_id="arix_btn_shuffle"
        )
        shuffle_btn.callback = self._shuffle_callback
        self.add_item(shuffle_btn)

        # Loop (Toggle Off -> Song -> Queue)
        loop_mode = self.player.loop_mode
        loop_style = discord.ButtonStyle.primary if loop_mode != "off" else discord.ButtonStyle.secondary
        loop_btn = Button(
            emoji=BrandConfig.EMOJI_LOOP,
            label=f"Loop: {loop_mode.capitalize()}",
            style=loop_style,
            row=1,
            custom_id="arix_btn_loop"
        )
        loop_btn.callback = self._loop_callback
        self.add_item(loop_btn)

        # Autoplay
        auto_style = discord.ButtonStyle.success if self.player.autoplay else discord.ButtonStyle.secondary
        autoplay_btn = Button(
            emoji=BrandConfig.EMOJI_AUTOPLAY,
            label="Auto: ON" if self.player.autoplay else "Auto: OFF",
            style=auto_style,
            row=1,
            custom_id="arix_btn_autoplay"
        )
        autoplay_btn.callback = self._autoplay_callback
        self.add_item(autoplay_btn)

        # Volume
        vol_btn = Button(
            emoji=BrandConfig.EMOJI_VOLUME,
            label=f"{self.player.volume}%",
            style=discord.ButtonStyle.secondary,
            row=1,
            custom_id="arix_btn_volume"
        )
        vol_btn.callback = self._volume_callback
        self.add_item(vol_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Global guard for button interactions: user must be in the same voice channel."""
        try:
            MusicPermissionChecker.ensure_user_in_voice(interaction)
            MusicPermissionChecker.ensure_same_voice_channel(interaction)
            return True
        except (NotInVoiceChannelError, ChannelMismatchError) as err:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("Voice Channel Guard", str(err)),
                ephemeral=True
            )
            return False

    async def _prev_callback(self, interaction: discord.Interaction) -> None:
        if not self.player.history:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("No History", "No previously played tracks are available."),
                ephemeral=True
            )
            return

        await interaction.response.defer()
        prev = await self.player.previous()
        if prev:
            await interaction.followup.send(
                embed=ArixByteEmbeds.info("Replaying Previous", f"Returning to: **{prev.title}**"),
                ephemeral=True
            )

    async def _pause_resume_callback(self, interaction: discord.Interaction) -> None:
        if self.player.is_paused:
            await self.player.resume()
            msg = "Playback resumed."
        else:
            await self.player.pause()
            msg = "Playback paused."

        self._setup_buttons()
        # Edit the player embed message with updated view
        await interaction.response.edit_message(view=self)

    async def _skip_callback(self, interaction: discord.Interaction) -> None:
        has_perm = await MusicPermissionChecker.is_dj_or_admin(interaction, self.player.db_manager)
        if not has_perm:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.error("Permission Denied", "You need DJ role or Admin to skip tracks."),
                ephemeral=True
            )
            return

        skipped = await self.player.skip()
        if skipped:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.info("Track Skipped", f"⏭️ Skipped **{skipped.title}**."),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("Cannot Skip", "No track is currently playing."),
                ephemeral=True
            )

    async def _stop_callback(self, interaction: discord.Interaction) -> None:
        has_perm = await MusicPermissionChecker.is_dj_or_admin(interaction, self.player.db_manager)
        if not has_perm:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.error("Permission Denied", "You need DJ role or Admin to stop playback."),
                ephemeral=True
            )
            return

        await self.player.stop(clear_queue=True, disconnect=False)
        await interaction.response.send_message(
            embed=ArixByteEmbeds.success("Playback Stopped", "Cleared the queue and stopped playback."),
            ephemeral=True
        )

    async def _playlist_callback(self, interaction: discord.Interaction) -> None:
        if not self.player.current_track:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("No Track", "No track is playing to add to a playlist."),
                ephemeral=True
            )
            return

        from services.playlist_service import PlaylistService
        service = PlaylistService(self.player.db_manager)
        user_playlists = await service.list_user_playlists(interaction.user.id)
        server_playlists = await service.list_server_playlists(interaction.guild_id)

        all_playlists = user_playlists + server_playlists
        if not all_playlists:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.info(
                    "No Playlists Found",
                    "You don't have any playlists yet! Create one using `/playlist create <name>`."
                ),
                ephemeral=True
            )
            return

        view = AddToPlaylistView(player=self.player, playlists=all_playlists)
        await interaction.response.send_message(
            content="Choose a playlist to save the current song:",
            view=view,
            ephemeral=True
        )

    async def _shuffle_callback(self, interaction: discord.Interaction) -> None:
        if len(self.player.queue) < 2:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("Cannot Shuffle", "The queue must contain at least 2 tracks to shuffle."),
                ephemeral=True
            )
            return

        count = self.player.shuffle()
        await interaction.response.send_message(
            embed=ArixByteEmbeds.success("Queue Shuffled", f"🔀 Successfully randomized **{count}** upcoming tracks."),
            ephemeral=True
        )

    async def _loop_callback(self, interaction: discord.Interaction) -> None:
        new_mode = self.player.toggle_loop()
        self._setup_buttons()
        await interaction.response.edit_message(view=self)

    async def _autoplay_callback(self, interaction: discord.Interaction) -> None:
        state = self.player.toggle_autoplay()
        self._setup_buttons()
        await interaction.response.edit_message(view=self)

    async def _volume_callback(self, interaction: discord.Interaction) -> None:
        view = VolumeSelectView(self.player)
        await interaction.response.send_message(
            content=f"Select desired playback volume (Current: `{self.player.volume}%`):",
            view=view,
            ephemeral=True
        )
