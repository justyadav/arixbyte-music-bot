"""
ArixByte Music Bot - Multi-Guild Music Manager & Player State Machine
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import random
import time
from typing import Optional, Dict, List, Any, Deque

try:
    import discord
except ImportError:
    discord = None

from config import config, BrandConfig
from services.audio_provider import BaseAudioProvider, Track, create_ffmpeg_source
from database.mongo import MongoManager
from utils.errors import (
    ArixByteMusicError,
    QueueEmptyError,
    AudioProviderError
)
from utils.embeds import ArixByteEmbeds

logger = logging.getLogger("ArixByteMusic.MusicManager")


class LoopMode:
    OFF = "off"
    SONG = "song"
    QUEUE = "queue"

    ALL = (OFF, SONG, QUEUE)


class GuildPlayer:
    """
    Independent audio player state machine for a single Discord guild.
    Manages queue, track lifecycle, volume, loop modes, autoplay, and voice timeouts.
    """

    def __init__(
        self,
        guild_id: int,
        audio_provider: BaseAudioProvider,
        db_manager: MongoManager,
        bot: Any
    ):
        self.guild_id: int = guild_id
        self.audio_provider: BaseAudioProvider = audio_provider
        self.db_manager: MongoManager = db_manager
        self.bot: Any = bot

        # Playback states
        self.voice_client: Optional[discord.VoiceClient] = None
        self.text_channel: Optional[discord.TextChannel | discord.Thread] = None
        self.current_track: Optional[Track] = None
        self.queue: Deque[Track] = collections.deque()
        self.history: Deque[Track] = collections.deque(maxlen=30)

        # Settings & Modes
        self.volume: int = config.default_volume
        self.loop_mode: str = LoopMode.OFF
        self.autoplay: bool = False
        self.empty_timeout: int = config.empty_vc_timeout

        # Timing tracking
        self.playback_start_time: float = 0.0
        self.paused_at: float = 0.0
        self.total_paused_duration: float = 0.0
        self.is_manual_skip: bool = False

        # Internal tasks & synchronization
        self.lock: asyncio.Lock = asyncio.Lock()
        self.empty_vc_task: Optional[asyncio.Task] = None
        self.player_message: Optional[discord.Message] = None
        self._current_source: Optional[Any] = None

    @property
    def is_playing(self) -> bool:
        return self.voice_client is not None and self.voice_client.is_playing()

    @property
    def is_paused(self) -> bool:
        return self.voice_client is not None and self.voice_client.is_paused()

    @property
    def current_position(self) -> float:
        """Calculate elapsed playback time in seconds taking pauses into account."""
        if not self.current_track or self.playback_start_time == 0:
            return 0.0

        if self.is_paused:
            return max(0.0, self.paused_at - self.playback_start_time - self.total_paused_duration)

        now = time.time()
        elapsed = now - self.playback_start_time - self.total_paused_duration
        if self.current_track.duration > 0:
            return min(float(self.current_track.duration), max(0.0, elapsed))
        return max(0.0, elapsed)

    @property
    def remaining_duration(self) -> float:
        """Calculate remaining time for current song."""
        if not self.current_track or self.current_track.duration <= 0:
            return 0.0
        return max(0.0, self.current_track.duration - self.current_position)

    @property
    def queue_duration(self) -> int:
        return sum(t.duration for t in self.queue)

    def cancel_empty_timer(self) -> None:
        """Cancel pending auto-disconnect countdown if members rejoin or music starts."""
        if self.empty_vc_task and not self.empty_vc_task.done():
            self.empty_vc_task.cancel()
            self.empty_vc_task = None
            logger.debug("Cancelled empty voice channel timeout for guild %d", self.guild_id)

    def start_empty_timer(self, reason: str = "Voice channel empty") -> None:
        """Begin auto-disconnect countdown."""
        self.cancel_empty_timer()

        async def _timer():
            try:
                logger.info("Starting empty voice channel timer (%ds) for guild %d: %s", self.empty_timeout, self.guild_id, reason)
                await asyncio.sleep(self.empty_timeout)
                if self.voice_client and self.voice_client.is_connected():
                    if self.text_channel:
                        embed = ArixByteEmbeds.info(
                            "Disconnected",
                            f"Left the voice channel after {self.empty_timeout}s of inactivity. See you soon!"
                        )
                        await self.text_channel.send(embed=embed)
                    await self.stop(clear_queue=True, disconnect=True)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error("Error in empty timer task: %s", e)

        self.empty_vc_task = asyncio.create_task(_timer())

    async def connect(self, channel: discord.VoiceChannel | discord.StageChannel) -> discord.VoiceClient:
        """Connect or move to the specified voice channel."""
        self.cancel_empty_timer()
        if self.voice_client and self.voice_client.is_connected():
            if self.voice_client.channel.id != channel.id:
                await self.voice_client.move_to(channel)
            return self.voice_client

        self.voice_client = await channel.connect(reconnect=True, timeout=20.0)
        return self.voice_client

    async def enqueue(self, track: Track) -> int:
        """Add a track to the queue and return its position."""
        if len(self.queue) >= config.max_queue_length:
            raise ArixByteMusicError(f"Queue has reached the maximum capacity of {config.max_queue_length} tracks.")

        self.queue.append(track)
        return len(self.queue)

    async def enqueue_multiple(self, tracks: List[Track]) -> int:
        """Add multiple tracks to the queue (e.g. from a playlist)."""
        added = 0
        for track in tracks:
            if len(self.queue) >= config.max_queue_length:
                break
            self.queue.append(track)
            added += 1
        return added

    async def play_next(self, seek_seconds: Optional[int] = None) -> None:
        """Proceed to play the next track according to queue and loop rules."""
        async with self.lock:
            self.cancel_empty_timer()

            if not self.voice_client or not self.voice_client.is_connected():
                logger.debug("Voice client disconnected. Aborting play_next for guild %d", self.guild_id)
                return

            # Determine next track
            if seek_seconds is not None and self.current_track:
                # Replaying current track with offset
                next_track = self.current_track
            elif self.loop_mode == LoopMode.SONG and self.current_track and not self.is_manual_skip:
                next_track = self.current_track
            else:
                self.is_manual_skip = False
                if self.loop_mode == LoopMode.QUEUE and self.current_track:
                    self.queue.append(self.current_track)

                if self.current_track:
                    self.history.append(self.current_track)

                if self.queue:
                    next_track = self.queue.popleft()
                elif self.autoplay and self.current_track:
                    # Autoplay recommendation
                    next_track = await self._fetch_autoplay_track()
                else:
                    # Queue is empty and no autoplay
                    self.current_track = None
                    self._cleanup_player_message()
                    self.start_empty_timer("Queue finished")
                    return

            self.current_track = next_track
            await self._start_playback(next_track, seek_seconds=seek_seconds)

    async def _fetch_autoplay_track(self) -> Optional[Track]:
        """Fetch the next track using the audio provider's recommendation engine."""
        if not self.current_track:
            return None

        try:
            logger.info("Autoplay triggered for guild %d. Fetching recommendations for: %s", self.guild_id, self.current_track.title)
            history_urls = [t.url for t in self.history] + [self.current_track.url]
            candidates = await self.audio_provider.get_recommendations(self.current_track, history_urls)

            if candidates:
                rec_track = candidates[0]
                rec_track.requester = self.bot.user
                if self.text_channel:
                    embed = ArixByteEmbeds.info(
                        "Autoplay Recommendation",
                        f"✨ Queue finished. Autoplaying: **[{rec_track.title}]({rec_track.url})** by **{rec_track.artist}**"
                    )
                    await self.text_channel.send(embed=embed)
                return rec_track
            else:
                logger.info("No autoplay recommendations found for guild %d.", self.guild_id)
                if self.text_channel:
                    await self.text_channel.send(
                        embed=ArixByteEmbeds.warning(
                            "Autoplay Exhausted",
                            "No further recommendations could be found for the recent tracks. Playback stopped."
                        )
                    )
        except Exception as e:
            logger.error("Autoplay recommendation error: %s", e)

        return None

    async def _start_playback(self, track: Track, seek_seconds: Optional[int] = None) -> None:
        """Resolve media stream and play via FFmpeg with volume and controls."""
        try:
            stream_url = await self.audio_provider.get_stream_url(track)
            volume_scale = self.volume / 100.0

            source = create_ffmpeg_source(
                stream_url=stream_url,
                ffmpeg_path=config.ffmpeg_path,
                volume=volume_scale,
                seek_seconds=seek_seconds
            )
            self._current_source = source

            # Reset timestamps
            self.playback_start_time = time.time() - (seek_seconds or 0)
            self.paused_at = 0.0
            self.total_paused_duration = 0.0

            def _after(error):
                if error:
                    logger.error("Voice playback error in guild %d: %s", self.guild_id, error)
                coro = self.play_next()
                asyncio.run_coroutine_threadsafe(coro, self.bot.loop)

            if self.voice_client.is_playing() or self.voice_client.is_paused():
                self.voice_client.stop()

            self.voice_client.play(source, after=_after)
            await self._update_or_send_player_embed()

        except Exception as ex:
            logger.error("Failed to start playback for '%s': %s", track.title, ex)
            if self.text_channel:
                await self.text_channel.send(
                    embed=ArixByteEmbeds.error(
                        "Playback Error",
                        f"Failed to load stream for **{track.title}**: {ex}"
                    )
                )
            # Try next song
            await self.play_next()

    async def _update_or_send_player_embed(self) -> None:
        """Send or update the interactive player embed with button view."""
        if not self.text_channel or not self.current_track:
            return

        from cogs.player_buttons import PlayerControlView

        embed = ArixByteEmbeds.player_embed(
            track_title=self.current_track.title,
            artist=self.current_track.artist,
            url=self.current_track.url,
            thumbnail=self.current_track.thumbnail,
            duration=self.current_track.duration,
            current_position=self.current_position,
            is_paused=self.is_paused,
            volume=self.volume,
            loop_mode=self.loop_mode,
            autoplay=self.autoplay,
            queue_count=len(self.queue),
            queue_duration=self.queue_duration,
            requester=self.current_track.requester
        )

        view = PlayerControlView(player=self)

        try:
            # Check if previous message can be edited
            if self.player_message:
                try:
                    await self.player_message.edit(embed=embed, view=view)
                    return
                except discord.NotFound:
                    self.player_message = None
                except Exception as e:
                    logger.debug("Could not edit player message: %s", e)
                    self.player_message = None

            self.player_message = await self.text_channel.send(embed=embed, view=view)
        except Exception as e:
            logger.error("Failed to send player embed: %s", e)

    def _cleanup_player_message(self) -> None:
        """Disable buttons on finished player embed."""
        if self.player_message and self.bot.loop:
            async def _disable():
                try:
                    await self.player_message.edit(view=None)
                except Exception:
                    pass
            asyncio.create_task(_disable())
            self.player_message = None

    async def pause(self) -> bool:
        """Pause playback."""
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            self.paused_at = time.time()
            await self._update_or_send_player_embed()
            return True
        return False

    async def resume(self) -> bool:
        """Resume paused playback."""
        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()
            if self.paused_at > 0:
                self.total_paused_duration += time.time() - self.paused_at
                self.paused_at = 0.0
            await self._update_or_send_player_embed()
            return True
        return False

    async def skip(self) -> Optional[Track]:
        """Skip current track."""
        if not self.current_track:
            return None

        skipped = self.current_track
        self.is_manual_skip = True
        if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.voice_client.stop()
        else:
            await self.play_next()
        return skipped

    async def previous(self) -> Optional[Track]:
        """Replay the previous track from history."""
        if not self.history:
            return None

        prev_track = self.history.pop()
        # Prepend current track to front of queue if it exists
        if self.current_track:
            self.queue.appendleft(self.current_track)

        self.current_track = prev_track
        await self._start_playback(prev_track)
        return prev_track

    async def stop(self, clear_queue: bool = True, disconnect: bool = False) -> None:
        """Stop playback, optionally clearing queue and disconnecting."""
        self.cancel_empty_timer()
        if clear_queue:
            self.queue.clear()
            self.current_track = None

        if self.voice_client:
            if self.voice_client.is_playing() or self.voice_client.is_paused():
                self.voice_client.stop()

            if disconnect and self.voice_client.is_connected():
                await self.voice_client.disconnect(force=True)
                self.voice_client = None

        self._cleanup_player_message()

    async def set_volume(self, volume: int) -> int:
        """Adjust volume level between 1% and max_volume%."""
        volume = max(1, min(config.max_volume, volume))
        self.volume = volume

        if self._current_source and hasattr(self._current_source, "volume"):
            self._current_source.volume = volume / 100.0

        await self._update_or_send_player_embed()
        return self.volume

    async def seek(self, seconds: int) -> None:
        """Seek to a specific timestamp in the current song."""
        if not self.current_track:
            raise QueueEmptyError("No track is currently playing to seek.")

        if seconds < 0 or (self.current_track.duration > 0 and seconds > self.current_track.duration):
            raise ArixByteMusicError("Seek timestamp is out of range.")

        await self.play_next(seek_seconds=seconds)

    def shuffle(self) -> int:
        """Randomize queued tracks."""
        if not self.queue:
            raise QueueEmptyError("Queue is empty; nothing to shuffle.")
        queue_list = list(self.queue)
        random.shuffle(queue_list)
        self.queue = collections.deque(queue_list)
        return len(self.queue)

    def toggle_loop(self) -> str:
        """Cycle through loop modes: off -> song -> queue -> off."""
        if self.loop_mode == LoopMode.OFF:
            self.loop_mode = LoopMode.SONG
        elif self.loop_mode == LoopMode.SONG:
            self.loop_mode = LoopMode.QUEUE
        else:
            self.loop_mode = LoopMode.OFF
        return self.loop_mode

    def toggle_autoplay(self) -> bool:
        """Toggle autoplay recommendations on or off."""
        self.autoplay = not self.autoplay
        return self.autoplay


class MusicManager:
    """Multi-guild registry managing isolated GuildPlayer instances."""

    def __init__(self, bot: Any, audio_provider: BaseAudioProvider, db_manager: MongoManager):
        self.bot: Any = bot
        self.audio_provider: BaseAudioProvider = audio_provider
        self.db_manager: MongoManager = db_manager
        self.players: Dict[int, GuildPlayer] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    def get_player(self, guild_id: int) -> GuildPlayer:
        """Retrieve or construct the GuildPlayer for the requested guild."""
        if guild_id not in self.players:
            self.players[guild_id] = GuildPlayer(
                guild_id=guild_id,
                audio_provider=self.audio_provider,
                db_manager=self.db_manager,
                bot=self.bot
            )
        return self.players[guild_id]

    async def remove_player(self, guild_id: int) -> None:
        """Safely destroy and cleanup a guild player."""
        async with self._lock:
            player = self.players.pop(guild_id, None)
            if player:
                await player.stop(clear_queue=True, disconnect=True)

    async def cleanup_all(self) -> None:
        """Cleanup all players during bot shutdown."""
        logger.info("Cleaning up all active music players...")
        for guild_id, player in list(self.players.items()):
            try:
                await player.stop(clear_queue=True, disconnect=True)
            except Exception as e:
                logger.error("Error shutting down player for guild %d: %s", guild_id, e)
        self.players.clear()
