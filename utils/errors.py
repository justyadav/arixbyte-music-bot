"""
ArixByte Music Bot - Custom Exception Hierarchy
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations


class ArixByteMusicError(Exception):
    """Base exception for all ArixByte Music errors."""
    def __init__(self, message: str = "An unexpected music bot error occurred."):
        self.message = message
        super().__init__(self.message)


class VoiceConnectionError(ArixByteMusicError):
    """Raised when the bot or user fails voice channel connection validation."""
    pass


class NotInVoiceChannelError(VoiceConnectionError):
    """Raised when the user is not connected to a voice channel."""
    def __init__(self, message: str = "You must be connected to a voice channel to use this command."):
        super().__init__(message)


class ChannelMismatchError(VoiceConnectionError):
    """Raised when the user is in a different voice channel than the bot."""
    def __init__(self, message: str = "You must be in the same voice channel as ArixByte Music to control playback."):
        super().__init__(message)


class TrackNotFoundError(ArixByteMusicError):
    """Raised when a song query or URL returns no playable results."""
    def __init__(self, query: str = ""):
        msg = f"No playable audio found for: `{query}`" if query else "The requested track could not be found."
        super().__init__(msg)


class QueueEmptyError(ArixByteMusicError):
    """Raised when an operation requires an active queue but the queue is empty."""
    def __init__(self, message: str = "The queue is currently empty."):
        super().__init__(message)


class PlaylistError(ArixByteMusicError):
    """Base exception for playlist operations."""
    pass


class PlaylistNotFoundError(PlaylistError):
    """Raised when a specified playlist does not exist."""
    def __init__(self, name: str):
        super().__init__(f"Playlist `{name}` was not found.")


class PlaylistLimitReachedError(PlaylistError):
    """Raised when attempting to add tracks past the maximum allowed limit."""
    def __init__(self, limit: int):
        super().__init__(f"Playlist has reached the maximum capacity of {limit} tracks.")


class PermissionDeniedError(ArixByteMusicError):
    """Raised when a user lacks DJ or administrator permissions for a command."""
    def __init__(self, message: str = "You do not have permission to execute this music command."):
        super().__init__(message)


class AudioProviderError(ArixByteMusicError):
    """Raised when the underlying audio provider encounters an extraction or streaming error."""
    def __init__(self, details: str = "Audio backend stream failure."):
        super().__init__(f"Audio Provider Error: {details}")
