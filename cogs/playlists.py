"""
ArixByte Music Bot - Playlist Management Slash Commands Cog
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations

import logging
import math
from typing import Optional, List

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

from config import BrandConfig, config
from services.music_manager import MusicManager
from services.playlist_service import PlaylistService
from services.audio_provider import Track
from database.mongo import MongoManager
from database.models import PlaylistModel
from utils.permissions import MusicPermissionChecker
from utils.embeds import ArixByteEmbeds, format_duration
from utils.errors import (
    PlaylistNotFoundError,
    PlaylistLimitReachedError,
    PermissionDeniedError,
    ArixByteMusicError
)

logger = logging.getLogger("ArixByteMusic.PlaylistsCog")


class PlaylistPaginationView(View):
    """Paginated view for viewing tracks inside a large playlist."""

    def __init__(self, playlist: PlaylistModel, current_page: int = 1, page_size: int = 10):
        super().__init__(timeout=120)
        self.playlist = playlist
        self.current_page = current_page
        self.page_size = page_size
        self._update_buttons()

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(len(self.playlist.tracks) / self.page_size))

    def _update_buttons(self) -> None:
        self.clear_items()

        prev_btn = Button(emoji="⬅️", style=discord.ButtonStyle.secondary, disabled=self.current_page <= 1)
        prev_btn.callback = self._prev_page
        self.add_item(prev_btn)

        ind_btn = Button(label=f"Page {self.current_page} / {self.total_pages}", style=discord.ButtonStyle.primary, disabled=True)
        self.add_item(ind_btn)

        next_btn = Button(emoji="➡️", style=discord.ButtonStyle.secondary, disabled=self.current_page >= self.total_pages)
        next_btn.callback = self._next_page
        self.add_item(next_btn)

    def _render_embed(self) -> discord.Embed:
        start_idx = (self.current_page - 1) * self.page_size
        end_idx = start_idx + self.page_size
        sliced = self.playlist.tracks[start_idx:end_idx]

        embed = discord.Embed(
            title=f"📃 Playlist: {self.playlist.name}",
            description=f"Type: **{'Server Playlist' if self.playlist.is_server_playlist else 'Personal Playlist'}**\n"
                        f"Tracks: `{len(self.playlist.tracks)}` | Total Duration: `{format_duration(self.playlist.total_duration)}`",
            color=BrandConfig.COLOR_PRIMARY
        )

        if not self.playlist.tracks:
            embed.add_field(name="Tracks", value="*This playlist currently contains no tracks.*", inline=False)
        else:
            lines = []
            for i, track in enumerate(sliced, start=start_idx + 1):
                lines.append(f"`{i}.` **[{track.title[:55]}]({track.url})** — `{format_duration(track.duration)}`")
            embed.add_field(
                name=f"Tracks (Page {self.current_page}/{self.total_pages})",
                value="\n".join(lines),
                inline=False
            )

        footer_suffix = f"Page {self.current_page}/{self.total_pages} • {len(self.playlist.tracks)} tracks"
        return ArixByteEmbeds._apply_branding(embed, footer_suffix=footer_suffix)

    async def _prev_page(self, interaction: discord.Interaction):
        if self.current_page > 1:
            self.current_page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._render_embed(), view=self)

    async def _next_page(self, interaction: discord.Interaction):
        if self.current_page < self.total_pages:
            self.current_page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._render_embed(), view=self)


class PlaylistsCog(commands.GroupCog, name="playlist"):
    """Comprehensive playlist management group commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def music_manager(self) -> MusicManager:
        return self.bot.music_manager

    @property
    def db_manager(self) -> MongoManager:
        return self.bot.db_manager

    @property
    def playlist_service(self) -> PlaylistService:
        return PlaylistService(self.db_manager)

    async def _playlist_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete available playlists for the user."""
        try:
            user_playlists = await self.playlist_service.list_user_playlists(interaction.user.id)
            server_playlists = await self.playlist_service.list_server_playlists(interaction.guild_id)
            all_pl = user_playlists + server_playlists

            choices = []
            for pl in all_pl:
                if current.lower() in pl.name.lower():
                    scope = "Server" if pl.is_server_playlist else "Personal"
                    choices.append(app_commands.Choice(
                        name=f"{pl.name} ({scope} - {len(pl.tracks)} songs)",
                        value=pl.name
                    ))
            return choices[:25]
        except Exception:
            return []

    # -------------------------------------------------------------------------
    # /playlist create
    # -------------------------------------------------------------------------
    @app_commands.command(name="create", description="Create a new personal or server playlist.")
    @app_commands.describe(
        name="Name for the playlist",
        server_playlist="Whether this playlist belongs to the server (requires Manage Server)"
    )
    async def create(self, interaction: discord.Interaction, name: str, server_playlist: bool = False):
        if server_playlist:
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message(
                    embed=ArixByteEmbeds.error("Permission Denied", "You need Manage Server permissions to create a server playlist."),
                    ephemeral=True
                )
                return

        try:
            pl = await self.playlist_service.create_playlist(
                name=name,
                owner_id=interaction.user.id,
                guild_id=interaction.guild_id if server_playlist else None,
                is_server_playlist=server_playlist
            )
            embed = ArixByteEmbeds.success(
                "Playlist Created",
                f"Successfully created **{'Server' if server_playlist else 'Personal'}** playlist: **{pl.name}**.\n"
                f"Add tracks with `/playlist add {pl.name} <query>` or via the player button!"
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.error("Playlist Creation Error", str(e)),
                ephemeral=True
            )

    # -------------------------------------------------------------------------
    # /playlist add
    # -------------------------------------------------------------------------
    @app_commands.command(name="add", description="Add a song or URL to a playlist.")
    @app_commands.describe(name="Playlist name", query="Song title, artist, or direct media URL")
    @app_commands.autocomplete(name=_playlist_autocomplete)
    async def add(self, interaction: discord.Interaction, name: str, query: str):
        await interaction.response.defer()

        # Find if it is server or user playlist
        pl = await self.db_manager.get_playlist(name=name, owner_id=interaction.user.id, server_playlist=False)
        is_server = False
        if not pl:
            pl = await self.db_manager.get_playlist(name=name, guild_id=interaction.guild_id, server_playlist=True)
            is_server = True

        if not pl:
            await interaction.followup.send(
                embed=ArixByteEmbeds.error("Not Found", f"Playlist `{name}` was not found.")
            )
            return

        if is_server and not interaction.user.guild_permissions.manage_guild:
            is_dj = await MusicPermissionChecker.is_dj_or_admin(interaction, self.db_manager)
            if not is_dj:
                await interaction.followup.send(
                    embed=ArixByteEmbeds.error("Permission Denied", "You need DJ role or Manage Server to edit server playlists.")
                )
                return

        player = self.music_manager.get_player(interaction.guild_id)
        try:
            tracks = await player.audio_provider.search(query, requester=interaction.user)
            if not tracks:
                raise ArixByteMusicError("No playable tracks found for your search query.")

            track = tracks[0]
            updated_pl = await self.playlist_service.add_track(
                name=pl.name,
                track=track,
                owner_id=interaction.user.id if not is_server else None,
                guild_id=interaction.guild_id if is_server else None,
                is_server_playlist=is_server
            )

            embed = ArixByteEmbeds.success(
                "Track Added",
                f"Added **[{track.title}]({track.url})** to **{updated_pl.name}**.\n"
                f"Total tracks in playlist: `{len(updated_pl.tracks)}`"
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(
                embed=ArixByteEmbeds.error("Add Track Error", str(e))
            )

    # -------------------------------------------------------------------------
    # /playlist remove
    # -------------------------------------------------------------------------
    @app_commands.command(name="remove", description="Remove a track from a playlist by its track number.")
    @app_commands.describe(name="Playlist name", index="Track number in the playlist (e.g. 1)")
    @app_commands.autocomplete(name=_playlist_autocomplete)
    async def remove(self, interaction: discord.Interaction, name: str, index: int):
        pl = await self.db_manager.get_playlist(name=name, owner_id=interaction.user.id, server_playlist=False)
        is_server = False
        if not pl:
            pl = await self.db_manager.get_playlist(name=name, guild_id=interaction.guild_id, server_playlist=True)
            is_server = True

        if not pl:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.error("Not Found", f"Playlist `{name}` was not found."),
                ephemeral=True
            )
            return

        if is_server and not interaction.user.guild_permissions.manage_guild:
            is_dj = await MusicPermissionChecker.is_dj_or_admin(interaction, self.db_manager)
            if not is_dj:
                await interaction.response.send_message(
                    embed=ArixByteEmbeds.error("Permission Denied", "You need DJ role or Manage Server to edit server playlists."),
                    ephemeral=True
                )
                return

        try:
            updated_pl, removed_track = await self.playlist_service.remove_track(
                name=pl.name,
                index=index,
                owner_id=interaction.user.id if not is_server else None,
                guild_id=interaction.guild_id if is_server else None,
                is_server_playlist=is_server
            )
            embed = ArixByteEmbeds.success(
                "Track Removed",
                f"Removed **{removed_track.title}** (Track #{index}) from **{updated_pl.name}**.\n"
                f"Remaining tracks: `{len(updated_pl.tracks)}`"
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.error("Remove Track Error", str(e)),
                ephemeral=True
            )

    # -------------------------------------------------------------------------
    # /playlist view
    # -------------------------------------------------------------------------
    @app_commands.command(name="view", description="View tracks and details in a playlist.")
    @app_commands.describe(name="Playlist name", page="Page number")
    @app_commands.autocomplete(name=_playlist_autocomplete)
    async def view(self, interaction: discord.Interaction, name: str, page: Optional[int] = 1):
        pl = await self.db_manager.get_playlist(name=name, owner_id=interaction.user.id, server_playlist=False)
        if not pl:
            pl = await self.db_manager.get_playlist(name=name, guild_id=interaction.guild_id, server_playlist=True)

        if not pl:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.error("Not Found", f"Playlist `{name}` was not found."),
                ephemeral=True
            )
            return

        target_page = max(1, page or 1)
        view = PlaylistPaginationView(playlist=pl, current_page=target_page, page_size=10)
        embed = view._render_embed()
        await interaction.response.send_message(embed=embed, view=view)

    # -------------------------------------------------------------------------
    # /playlist play
    # -------------------------------------------------------------------------
    @app_commands.command(name="play", description="Load and play all tracks from a playlist.")
    @app_commands.describe(name="Playlist name")
    @app_commands.autocomplete(name=_playlist_autocomplete)
    async def play(self, interaction: discord.Interaction, name: str):
        voice_channel = MusicPermissionChecker.ensure_user_in_voice(interaction)
        player = self.music_manager.get_player(interaction.guild_id)

        await interaction.response.defer()

        # Connect to voice channel
        if not player.voice_client or not player.voice_client.is_connected():
            await player.connect(voice_channel)
        else:
            MusicPermissionChecker.ensure_same_voice_channel(interaction)

        player.text_channel = interaction.channel

        pl = await self.db_manager.get_playlist(name=name, owner_id=interaction.user.id, server_playlist=False)
        if not pl:
            pl = await self.db_manager.get_playlist(name=name, guild_id=interaction.guild_id, server_playlist=True)

        if not pl:
            await interaction.followup.send(
                embed=ArixByteEmbeds.error("Not Found", f"Playlist `{name}` was not found.")
            )
            return

        if not pl.tracks:
            await interaction.followup.send(
                embed=ArixByteEmbeds.warning("Playlist Empty", f"Playlist `{pl.name}` contains no tracks to play.")
            )
            return

        converted_tracks = [
            Track(
                id=f"pl_{idx}",
                title=t.title,
                artist=t.artist,
                url=t.url,
                duration=t.duration,
                thumbnail=t.thumbnail,
                requester=interaction.user
            )
            for idx, t in enumerate(pl.tracks)
        ]

        added = await player.enqueue_multiple(converted_tracks)
        embed = ArixByteEmbeds.success(
            "Playlist Queued",
            f"Loaded **{added}** tracks from playlist **{pl.name}** into the queue!\n"
            f"Total duration: `{format_duration(pl.total_duration)}`"
        )
        await interaction.followup.send(embed=embed)

        if not player.is_playing and not player.is_paused and not player.current_track:
            await player.play_next()

    # -------------------------------------------------------------------------
    # /playlist delete
    # -------------------------------------------------------------------------
    @app_commands.command(name="delete", description="Permanently delete a playlist.")
    @app_commands.describe(name="Playlist name")
    @app_commands.autocomplete(name=_playlist_autocomplete)
    async def delete(self, interaction: discord.Interaction, name: str):
        pl = await self.db_manager.get_playlist(name=name, owner_id=interaction.user.id, server_playlist=False)
        is_server = False
        if not pl:
            pl = await self.db_manager.get_playlist(name=name, guild_id=interaction.guild_id, server_playlist=True)
            is_server = True

        if not pl:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.error("Not Found", f"Playlist `{name}` was not found."),
                ephemeral=True
            )
            return

        if is_server and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.error("Permission Denied", "Only administrators can delete server playlists."),
                ephemeral=True
            )
            return

        success = await self.playlist_service.delete_playlist(
            name=pl.name,
            owner_id=interaction.user.id if not is_server else None,
            guild_id=interaction.guild_id if is_server else None,
            is_server_playlist=is_server
        )

        if success:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.success("Playlist Deleted", f"🗑️ Deleted playlist **{pl.name}**.")
            )
        else:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.error("Delete Failed", "Could not delete playlist from database."),
                ephemeral=True
            )

    # -------------------------------------------------------------------------
    # /playlist list
    # -------------------------------------------------------------------------
    @app_commands.command(name="list", description="List your personal playlists and server playlists.")
    async def list(self, interaction: discord.Interaction):
        user_playlists = await self.playlist_service.list_user_playlists(interaction.user.id)
        server_playlists = await self.playlist_service.list_server_playlists(interaction.guild_id)

        embed = discord.Embed(
            title=f"{BrandConfig.NAME} — Playlists",
            color=BrandConfig.COLOR_PRIMARY
        )

        # Personal section
        if user_playlists:
            user_text = "\n".join(
                f"• **{p.name}** — `{len(p.tracks)} tracks` ({format_duration(p.total_duration)})"
                for p in user_playlists
            )
        else:
            user_text = "*You haven't created any personal playlists yet.*"
        embed.add_field(name="👤 Your Personal Playlists", value=user_text, inline=False)

        # Server section
        if server_playlists:
            server_text = "\n".join(
                f"• **{p.name}** — `{len(p.tracks)} tracks` ({format_duration(p.total_duration)})"
                for p in server_playlists
            )
        else:
            server_text = "*No server playlists configured.*"
        embed.add_field(name="🌐 Server Playlists", value=server_text, inline=False)

        ArixByteEmbeds._apply_branding(embed)
        await interaction.response.send_message(embed=embed)

    # -------------------------------------------------------------------------
    # /playlist shuffle
    # -------------------------------------------------------------------------
    @app_commands.command(name="shuffle", description="Shuffle all songs within a saved playlist.")
    @app_commands.describe(name="Playlist name")
    @app_commands.autocomplete(name=_playlist_autocomplete)
    async def shuffle(self, interaction: discord.Interaction, name: str):
        pl = await self.db_manager.get_playlist(name=name, owner_id=interaction.user.id, server_playlist=False)
        is_server = False
        if not pl:
            pl = await self.db_manager.get_playlist(name=name, guild_id=interaction.guild_id, server_playlist=True)
            is_server = True

        if not pl:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.error("Not Found", f"Playlist `{name}` was not found."),
                ephemeral=True
            )
            return

        if is_server and not interaction.user.guild_permissions.manage_guild:
            is_dj = await MusicPermissionChecker.is_dj_or_admin(interaction, self.db_manager)
            if not is_dj:
                await interaction.response.send_message(
                    embed=ArixByteEmbeds.error("Permission Denied", "You need DJ role or Manage Server to shuffle server playlists."),
                    ephemeral=True
                )
                return

        try:
            updated = await self.playlist_service.shuffle_playlist(
                name=pl.name,
                owner_id=interaction.user.id if not is_server else None,
                guild_id=interaction.guild_id if is_server else None,
                is_server_playlist=is_server
            )
            await interaction.response.send_message(
                embed=ArixByteEmbeds.success("Playlist Shuffled", f"🔀 Shuffled all `{len(updated.tracks)}` tracks in **{updated.name}**.")
            )
        except Exception as e:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.error("Shuffle Error", str(e)),
                ephemeral=True
            )

    # -------------------------------------------------------------------------
    # /playlist import
    # -------------------------------------------------------------------------
    @app_commands.command(name="import", description="Import an external playlist from a YouTube/SoundCloud URL into MongoDB.")
    @app_commands.describe(name="New playlist name", url="Playlist URL to import")
    async def import_playlist(self, interaction: discord.Interaction, name: str, url: str):
        await interaction.response.defer()
        player = self.music_manager.get_player(interaction.guild_id)

        try:
            tracks = await player.audio_provider.search(url, requester=interaction.user)
            if not tracks:
                raise ArixByteMusicError("Could not extract any tracks from the provided playlist URL.")

            # Create the playlist
            pl = await self.playlist_service.create_playlist(
                name=name,
                owner_id=interaction.user.id,
                guild_id=None,
                is_server_playlist=False
            )

            # Add extracted tracks
            added_count = 0
            for t in tracks[:config.max_playlist_tracks]:
                await self.playlist_service.add_track(
                    name=pl.name,
                    track=t,
                    owner_id=interaction.user.id,
                    is_server_playlist=False
                )
                added_count += 1

            embed = ArixByteEmbeds.success(
                "Playlist Imported",
                f"📥 Successfully imported **{added_count}** tracks into new playlist **{name}**!\n"
                f"Play anytime using `/playlist play {name}`."
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(
                embed=ArixByteEmbeds.error("Import Failed", str(e))
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(PlaylistsCog(bot))
