"""
ArixByte Music Bot - Playback Commands Cog
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations

import logging
import re
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
from utils.permissions import MusicPermissionChecker
from utils.embeds import ArixByteEmbeds, format_duration
from utils.errors import (
    NotInVoiceChannelError,
    ChannelMismatchError,
    PermissionDeniedError,
    TrackNotFoundError,
    ArixByteMusicError
)

logger = logging.getLogger("ArixByteMusic.PlaybackCog")


def parse_time_string(time_str: str) -> int:
    """Parse time string like '1:30', '01:25:00', or raw seconds '90' into total seconds."""
    time_str = time_str.strip()
    if time_str.isdigit():
        return int(time_str)

    parts = time_str.split(":")
    if len(parts) == 2:
        # MM:SS
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 3:
        # HH:MM:SS
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    raise ValueError("Invalid time format. Use seconds (e.g. 90) or MM:SS (e.g. 1:30).")


class PlaybackCog(commands.Cog, name="Playback"):
    """Core audio playback and stream manipulation commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def music_manager(self) -> MusicManager:
        return self.bot.music_manager

    @property
    def db_manager(self) -> MongoManager:
        return self.bot.db_manager

    # -------------------------------------------------------------------------
    # /play command
    # -------------------------------------------------------------------------
    @app_commands.command(name="play", description="Play music from a search query, video URL, or playlist link.")
    @app_commands.describe(query="Song title, artist, or direct audio link")
    async def play(self, interaction: discord.Interaction, query: str):
        voice_channel = MusicPermissionChecker.ensure_user_in_voice(interaction)
        player = self.music_manager.get_player(interaction.guild_id)

        await interaction.response.defer()

        # Connect to voice if not already connected
        if not player.voice_client or not player.voice_client.is_connected():
            await player.connect(voice_channel)
        else:
            MusicPermissionChecker.ensure_same_voice_channel(interaction)

        player.text_channel = interaction.channel

        try:
            tracks = await player.audio_provider.search(query, requester=interaction.user)
            if not tracks:
                raise TrackNotFoundError(query)

            if len(tracks) == 1:
                track = tracks[0]
                was_playing = player.is_playing or player.is_paused

                pos = await player.enqueue(track)
                if not was_playing and not player.current_track:
                    await interaction.followup.send(
                        embed=ArixByteEmbeds.info("Loading Track", f"🔍 Resolving stream for **{track.title}**...")
                    )
                    await player.play_next()
                else:
                    await interaction.followup.send(
                        embed=ArixByteEmbeds.track_enqueued(
                            title=track.title,
                            artist=track.artist,
                            url=track.url,
                            duration=track.duration,
                            thumbnail=track.thumbnail,
                            queue_position=pos,
                            requester=interaction.user
                        )
                    )
            else:
                # Multiple tracks / Playlist detected
                added_count = await player.enqueue_multiple(tracks)
                was_playing = player.is_playing or player.is_paused

                embed = ArixByteEmbeds.success(
                    "Playlist Queued",
                    f"Successfully loaded **{added_count}** tracks into the queue.\nFirst: **[{tracks[0].title}]({tracks[0].url})**"
                )
                await interaction.followup.send(embed=embed)

                if not was_playing and not player.current_track:
                    await player.play_next()

        except Exception as e:
            logger.error("Error in /play command: %s", e)
            await interaction.followup.send(
                embed=ArixByteEmbeds.error("Playback Failed", str(e))
            )

    # -------------------------------------------------------------------------
    # /pause and /resume
    # -------------------------------------------------------------------------
    @app_commands.command(name="pause", description="Pause current music playback.")
    async def pause(self, interaction: discord.Interaction):
        await MusicPermissionChecker.require_playback_control(interaction, self.db_manager)
        player = self.music_manager.get_player(interaction.guild_id)

        if not player.is_playing:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("Playback State", "Music is not currently playing."),
                ephemeral=True
            )
            return

        success = await player.pause()
        if success:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.info("Playback Paused", "⏸️ Music playback has been paused.")
            )

    @app_commands.command(name="resume", description="Resume paused music playback.")
    async def resume(self, interaction: discord.Interaction):
        await MusicPermissionChecker.require_playback_control(interaction, self.db_manager)
        player = self.music_manager.get_player(interaction.guild_id)

        if not player.is_paused:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("Playback State", "Playback is not currently paused."),
                ephemeral=True
            )
            return

        success = await player.resume()
        if success:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.info("Playback Resumed", "▶️ Music playback has resumed.")
            )

    # -------------------------------------------------------------------------
    # /skip and /previous
    # -------------------------------------------------------------------------
    @app_commands.command(name="skip", description="Skip the currently playing track.")
    async def skip(self, interaction: discord.Interaction):
        await MusicPermissionChecker.require_playback_control(interaction, self.db_manager)
        player = self.music_manager.get_player(interaction.guild_id)

        if not player.current_track:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("Cannot Skip", "No track is currently playing."),
                ephemeral=True
            )
            return

        skipped = await player.skip()
        await interaction.response.send_message(
            embed=ArixByteEmbeds.info("Track Skipped", f"⏭️ Skipped **{skipped.title}**.")
        )

    @app_commands.command(name="previous", description="Replay the previous track from history.")
    async def previous(self, interaction: discord.Interaction):
        await MusicPermissionChecker.require_playback_control(interaction, self.db_manager)
        player = self.music_manager.get_player(interaction.guild_id)

        if not player.history:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("No History", "No previously played tracks are available in history."),
                ephemeral=True
            )
            return

        await interaction.response.defer()
        prev = await player.previous()
        await interaction.followup.send(
            embed=ArixByteEmbeds.info("Replaying Previous Track", f"⏮️ Replaying **{prev.title}**.")
        )

    # -------------------------------------------------------------------------
    # /stop
    # -------------------------------------------------------------------------
    @app_commands.command(name="stop", description="Stop playback and clear the queue.")
    async def stop(self, interaction: discord.Interaction):
        await MusicPermissionChecker.require_playback_control(interaction, self.db_manager)
        player = self.music_manager.get_player(interaction.guild_id)

        await player.stop(clear_queue=True, disconnect=False)
        await interaction.response.send_message(
            embed=ArixByteEmbeds.success("Playback Stopped", "⏹️ Stopped playback and cleared the upcoming queue.")
        )

    # -------------------------------------------------------------------------
    # /nowplaying
    # -------------------------------------------------------------------------
    @app_commands.command(name="nowplaying", description="Show detailed info about the currently playing song.")
    async def nowplaying(self, interaction: discord.Interaction):
        player = self.music_manager.get_player(interaction.guild_id)

        if not player.current_track:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("Nothing Playing", "No music is currently playing in this server."),
                ephemeral=True
            )
            return

        embed = ArixByteEmbeds.player_embed(
            track_title=player.current_track.title,
            artist=player.current_track.artist,
            url=player.current_track.url,
            thumbnail=player.current_track.thumbnail,
            duration=player.current_track.duration,
            current_position=player.current_position,
            is_paused=player.is_paused,
            volume=player.volume,
            loop_mode=player.loop_mode,
            autoplay=player.autoplay,
            queue_count=len(player.queue),
            queue_duration=player.queue_duration,
            requester=player.current_track.requester
        )
        await interaction.response.send_message(embed=embed)

    # -------------------------------------------------------------------------
    # /volume
    # -------------------------------------------------------------------------
    @app_commands.command(name="volume", description="Adjust playback volume level (1-200%).")
    @app_commands.describe(level="Volume percentage between 1 and 200")
    async def volume(self, interaction: discord.Interaction, level: int):
        await MusicPermissionChecker.require_playback_control(interaction, self.db_manager)
        player = self.music_manager.get_player(interaction.guild_id)

        if level < 1 or level > config.max_volume:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("Invalid Volume", f"Volume must be set between 1% and {config.max_volume}%."),
                ephemeral=True
            )
            return

        new_vol = await player.set_volume(level)
        await interaction.response.send_message(
            embed=ArixByteEmbeds.success("Volume Set", f"🔊 Playback volume adjusted to **{new_vol}%**.")
        )

    # -------------------------------------------------------------------------
    # /seek
    # -------------------------------------------------------------------------
    @app_commands.command(name="seek", description="Seek to a position in the current track (e.g. 1:30 or 90).")
    @app_commands.describe(time="Time format in seconds (e.g. 90) or MM:SS (e.g. 1:30)")
    async def seek(self, interaction: discord.Interaction, time: str):
        await MusicPermissionChecker.require_playback_control(interaction, self.db_manager)
        player = self.music_manager.get_player(interaction.guild_id)

        if not player.current_track:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("Nothing Playing", "No track is playing to seek."),
                ephemeral=True
            )
            return

        try:
            seconds = parse_time_string(time)
        except ValueError as e:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("Invalid Time Format", str(e)),
                ephemeral=True
            )
            return

        if seconds > player.current_track.duration and player.current_track.duration > 0:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning(
                    "Out of Bounds",
                    f"Timestamp `{format_duration(seconds)}` exceeds song length `{format_duration(player.current_track.duration)}`."
                ),
                ephemeral=True
            )
            return

        await interaction.response.defer()
        try:
            await player.seek(seconds)
            await interaction.followup.send(
                embed=ArixByteEmbeds.success("Seek Successful", f"⏩ Seeked to `{format_duration(seconds)}`.")
            )
        except Exception as e:
            await interaction.followup.send(
                embed=ArixByteEmbeds.error("Seek Failed", str(e))
            )

    # -------------------------------------------------------------------------
    # /join and /leave
    # -------------------------------------------------------------------------
    @app_commands.command(name="join", description="Summon ArixByte Music to your voice channel.")
    async def join(self, interaction: discord.Interaction):
        voice_channel = MusicPermissionChecker.ensure_user_in_voice(interaction)
        player = self.music_manager.get_player(interaction.guild_id)

        await player.connect(voice_channel)
        player.text_channel = interaction.channel
        await interaction.response.send_message(
            embed=ArixByteEmbeds.success("Connected", f"Joined {voice_channel.mention}. Ready to play music!")
        )

    @app_commands.command(name="leave", description="Disconnect ArixByte Music from voice channel.")
    async def leave(self, interaction: discord.Interaction):
        await MusicPermissionChecker.require_playback_control(interaction, self.db_manager)
        player = self.music_manager.get_player(interaction.guild_id)

        if not player.voice_client:
            await interaction.response.send_message(
                embed=ArixByteEmbeds.warning("Not Connected", "I am not connected to any voice channel."),
                ephemeral=True
            )
            return

        await player.stop(clear_queue=True, disconnect=True)
        await interaction.response.send_message(
            embed=ArixByteEmbeds.info("Disconnected", "Left the voice channel and cleared playback state.")
        )

    # -------------------------------------------------------------------------
    # /lyrics
    # -------------------------------------------------------------------------
    @app_commands.command(name="lyrics", description="Fetch song lyrics for the current song or a search query.")
    @app_commands.describe(query="Optional song title or artist. Defaults to currently playing song.")
    async def lyrics(self, interaction: discord.Interaction, query: Optional[str] = None):
        player = self.music_manager.get_player(interaction.guild_id)

        search_query = query
        if not search_query:
            if player.current_track:
                search_query = f"{player.current_track.artist} - {player.current_track.title}"
            else:
                await interaction.response.send_message(
                    embed=ArixByteEmbeds.warning("No Query Provided", "Please specify a song title or play a song first."),
                    ephemeral=True
                )
                return

        await interaction.response.defer()

        # Legitimate lyrics lookup via Genius or public API
        if not config.genius_api_token:
            embed = ArixByteEmbeds.info(
                "Lyrics Provider Notice",
                f"Lyrics API integration requires `GENIUS_API_TOKEN` configured in `.env`.\n"
                f"Searched query: **{search_query}**\n"
                f"Visit [Genius API](https://genius.com/api-clients) to configure a legitimate token on ArixByte hosting."
            )
            await interaction.followup.send(embed=embed)
            return

        try:
            import aiohttp
            headers = {"Authorization": f"Bearer {config.genius_api_token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.genius.com/search?q={search_query}",
                    headers=headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        hits = data.get("response", {}).get("hits", [])
                        if hits:
                            top_hit = hits[0].get("result", {})
                            title = top_hit.get("full_title", search_query)
                            url = top_hit.get("url", "")
                            thumbnail = top_hit.get("song_art_image_thumbnail_url")

                            embed = discord.Embed(
                                title=f"Lyrics: {title}",
                                url=url,
                                description=f"Due to lyrics copyright restrictions, read full verified lyrics on [Genius.com]({url}).",
                                color=BrandConfig.COLOR_PRIMARY
                            )
                            if thumbnail:
                                embed.set_thumbnail(url=thumbnail)
                            ArixByteEmbeds._apply_branding(embed)
                            await interaction.followup.send(embed=embed)
                            return

            await interaction.followup.send(
                embed=ArixByteEmbeds.warning("Lyrics Not Found", f"No lyrics match found for: `{search_query}`")
            )
        except Exception as e:
            logger.error("Genius API lyrics error: %s", e)
            await interaction.followup.send(
                embed=ArixByteEmbeds.error("Lyrics Service Error", "Failed to retrieve lyrics from provider.")
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(PlaybackCog(bot))
