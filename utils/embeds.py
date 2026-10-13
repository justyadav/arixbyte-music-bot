"""
ArixByte Music Bot - Branded Discord Embed System
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations

import math
from typing import Optional, List, Any

try:
    import discord
except ImportError:
    discord = None

from config import BrandConfig


def format_duration(seconds: int | float) -> str:
    """Format total seconds into HH:MM:SS or MM:SS."""
    if seconds is None or seconds < 0:
        return "Live Stream"
    
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def create_progress_bar(
    current_sec: float,
    total_sec: float,
    bar_length: int = 14
) -> str:
    """Render a sleek, mobile-friendly visual audio progress bar."""
    if total_sec <= 0:
        return "🔴 [● LIVE STREAM ●]"

    progress = max(0.0, min(1.0, current_sec / total_sec))
    indicator_pos = int(progress * bar_length)

    bar = ""
    for i in range(bar_length):
        if i == indicator_pos:
            bar += "🔘"
        elif i < indicator_pos:
            bar += "▬"
        else:
            bar += "─"

    cur_formatted = format_duration(current_sec)
    tot_formatted = format_duration(total_sec)
    remaining_sec = max(0, total_sec - current_sec)
    rem_formatted = format_duration(remaining_sec)

    return f"`{cur_formatted}` {bar} `{tot_formatted}` *( -{rem_formatted} )*"


class ArixByteEmbeds:
    """Factory for generating consistent, high-fidelity ArixByte Ltd. branded embeds."""

    @staticmethod
    def _apply_branding(embed: Any, footer_suffix: Optional[str] = None) -> Any:
        """Apply uniform ArixByte brand footer and visual identity."""
        if embed is None:
            return None
        footer_text = f"{BrandConfig.NAME} • {BrandConfig.COMPANY} • {BrandConfig.TAGLINE}"
        if footer_suffix:
            footer_text = f"{footer_text} | {footer_suffix}"
        
        embed.set_footer(
            text=footer_text,
            icon_url=BrandConfig.ICON_LOGO
        )
        return embed

    @classmethod
    def player_embed(
        cls,
        track_title: str,
        artist: str,
        url: str,
        thumbnail: Optional[str],
        duration: int,
        current_position: float,
        is_paused: bool,
        volume: int,
        loop_mode: str,
        autoplay: bool,
        queue_count: int,
        queue_duration: int,
        requester: Optional[Any] = None
    ) -> Any:
        """Create the central interactive music player embed."""
        if discord is None:
            return None

        # Use deep purple or blurple accent
        color = BrandConfig.COLOR_SECONDARY if not is_paused else BrandConfig.COLOR_DARK
        embed = discord.Embed(
            title=f"{BrandConfig.EMOJI_MUSIC} Now Playing",
            description=f"**[{track_title}]({url})**\nby **{artist}**",
            color=color
        )

        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        # Progress bar
        progress_bar = create_progress_bar(current_position, duration)
        embed.add_field(
            name="Playback Progress",
            value=progress_bar,
            inline=False
        )

        # Status & Controls summary
        status_text = f"{BrandConfig.EMOJI_PAUSE} Paused" if is_paused else f"{BrandConfig.EMOJI_PLAY} Playing"
        loop_badge = f"{BrandConfig.EMOJI_LOOP} {loop_mode.capitalize()}"
        autoplay_badge = f"{BrandConfig.EMOJI_AUTOPLAY} ON" if autoplay else f"{BrandConfig.EMOJI_AUTOPLAY} OFF"
        volume_badge = f"{BrandConfig.EMOJI_VOLUME} {volume}%"

        embed.add_field(
            name="State & Modes",
            value=f"• **Status:** {status_text}\n• **Volume:** `{volume_badge}`\n• **Loop:** `{loop_badge}`\n• **Autoplay:** `{autoplay_badge}`",
            inline=True
        )

        # Queue info
        queue_info = f"• **Queued Tracks:** `{queue_count}`\n• **Queue Time:** `{format_duration(queue_duration)}`"
        if requester:
            mention = getattr(requester, "mention", getattr(requester, "name", "User"))
            queue_info += f"\n• **Requested by:** {mention}"

        embed.add_field(
            name="Queue Overview",
            value=queue_info,
            inline=True
        )

        return cls._apply_branding(embed)

    @classmethod
    def queue_embed(
        cls,
        current_track: Optional[Any],
        queue_tracks: List[Any],
        page: int = 1,
        page_size: int = 10,
        loop_mode: str = "off",
        autoplay: bool = False
    ) -> Any:
        """Generate a paginated queue view."""
        if discord is None:
            return None

        total_tracks = len(queue_tracks)
        total_pages = max(1, math.ceil(total_tracks / page_size))
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        sliced_tracks = queue_tracks[start_idx:end_idx]

        embed = discord.Embed(
            title=f"{BrandConfig.NAME} — Guild Queue",
            color=BrandConfig.COLOR_PRIMARY
        )

        if current_track:
            embed.add_field(
                name="💿 Currently Playing",
                value=f"**[{current_track.title}]({current_track.url})** ({format_duration(current_track.duration)})\nRequested by: {getattr(current_track.requester, 'mention', 'System')}",
                inline=False
            )

        if not queue_tracks:
            embed.description = "*The upcoming queue is currently empty. Add songs with `/play` or toggle Autoplay!*"
        else:
            lines = []
            for i, track in enumerate(sliced_tracks, start=start_idx + 1):
                req_name = getattr(track.requester, "display_name", "Unknown")
                lines.append(
                    f"`{i}.` **[{track.title[:50]}]({track.url})** — `{format_duration(track.duration)}` *(via {req_name})*"
                )
            embed.add_field(
                name=f"Upcoming Tracks (Page {page}/{total_pages})",
                value="\n".join(lines),
                inline=False
            )

        total_duration = sum(t.duration for t in queue_tracks)
        mode_text = f"Loop: `{loop_mode.capitalize()}` | Autoplay: `{'ON' if autoplay else 'OFF'}`"
        footer_suffix = f"Page {page}/{total_pages} • {total_tracks} tracks ({format_duration(total_duration)}) • {mode_text}"
        return cls._apply_branding(embed, footer_suffix=footer_suffix)

    @classmethod
    def track_enqueued(
        cls,
        title: str,
        artist: str,
        url: str,
        duration: int,
        thumbnail: Optional[str],
        queue_position: int,
        requester: Any
    ) -> Any:
        """Confirmation when a new track is added to the queue."""
        if discord is None:
            return None

        embed = discord.Embed(
            title=f"{BrandConfig.EMOJI_SUCCESS} Track Added to Queue",
            description=f"**[{title}]({url})**\nby **{artist}**",
            color=BrandConfig.COLOR_PRIMARY
        )
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        embed.add_field(name="Duration", value=f"`{format_duration(duration)}`", inline=True)
        embed.add_field(name="Position in Queue", value=f"`#{queue_position}`", inline=True)
        mention = getattr(requester, "mention", getattr(requester, "name", "User"))
        embed.add_field(name="Requester", value=mention, inline=True)

        return cls._apply_branding(embed)

    @classmethod
    def success(cls, title: str, description: str) -> Any:
        """Standard success notification."""
        if discord is None:
            return None
        embed = discord.Embed(
            title=f"{BrandConfig.EMOJI_SUCCESS} {title}",
            description=description,
            color=BrandConfig.COLOR_SUCCESS
        )
        return cls._apply_branding(embed)

    @classmethod
    def warning(cls, title: str, description: str) -> Any:
        """Standard warning notification."""
        if discord is None:
            return None
        embed = discord.Embed(
            title=f"{BrandConfig.EMOJI_WARNING} {title}",
            description=description,
            color=BrandConfig.COLOR_WARNING
        )
        return cls._apply_branding(embed)

    @classmethod
    def error(cls, title: str, description: str) -> Any:
        """Standard error notification."""
        if discord is None:
            return None
        embed = discord.Embed(
            title=f"{BrandConfig.EMOJI_ERROR} {title}",
            description=description,
            color=BrandConfig.COLOR_ERROR
        )
        return cls._apply_branding(embed)

    @classmethod
    def info(cls, title: str, description: str) -> Any:
        """Standard informational notification."""
        if discord is None:
            return None
        embed = discord.Embed(
            title=f"ℹ️ {title}",
            description=description,
            color=BrandConfig.COLOR_PRIMARY
        )
        return cls._apply_branding(embed)
