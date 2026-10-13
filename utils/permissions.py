"""
ArixByte Music Bot - Permissions & Voice State Guards
Company: ArixByte Ltd.
Tagline: Your Music. Your Community.
"""

from __future__ import annotations

import discord
from typing import Optional
from database.mongo import MongoManager
from database.models import GuildSettingsModel
from utils.errors import NotInVoiceChannelError, ChannelMismatchError, PermissionDeniedError


class MusicPermissionChecker:
    """Validates voice states, DJ roles, and administrative privileges."""

    @staticmethod
    def ensure_user_in_voice(interaction: discord.Interaction) -> discord.VoiceChannel | discord.StageChannel:
        """Verify that the invoking user is currently in a voice channel."""
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            raise NotInVoiceChannelError("This command can only be used in a server.")

        voice_state = interaction.user.voice
        if not voice_state or not voice_state.channel:
            raise NotInVoiceChannelError("You must connect to a voice channel before using this command.")

        return voice_state.channel

    @staticmethod
    def ensure_same_voice_channel(interaction: discord.Interaction) -> None:
        """Ensure that the invoking user is in the same voice channel as the bot."""
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            raise ChannelMismatchError("This command can only be used in a server.")

        bot_voice = interaction.guild.voice_client
        if not bot_voice or not bot_voice.channel:
            # Bot is not currently connected to any channel
            return

        user_voice = interaction.user.voice
        if not user_voice or not user_voice.channel:
            raise NotInVoiceChannelError("You must be in a voice channel to control music playback.")

        if user_voice.channel.id != bot_voice.channel.id:
            raise ChannelMismatchError(
                f"You must be connected to {bot_voice.channel.mention} to control current playback."
            )

    @staticmethod
    async def is_dj_or_admin(
        interaction: discord.Interaction,
        db_manager: MongoManager
    ) -> bool:
        """
        Check if user has DJ privileges or administrative rights.
        Returns True if:
        1. User has Administrator or Manage Guild permissions.
        2. User has the server's configured DJ role.
        3. User is alone with the bot in the voice channel (listenership authority).
        """
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return False

        member: discord.Member = interaction.user

        # Server administrators and managers always have full authority
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return True

        # Check voice channel loneliness: if only the user and the bot are in the VC, grant control
        if interaction.guild.voice_client and interaction.guild.voice_client.channel:
            members_in_vc = [
                m for m in interaction.guild.voice_client.channel.members if not m.bot
            ]
            if len(members_in_vc) <= 1:
                return True

        # Check DB settings for DJ role
        settings: GuildSettingsModel = await db_manager.get_guild_settings(interaction.guild.id)
        if not settings.dj_role_id:
            # No DJ role restricted, standard users are allowed by default unless dj_only_controls is strictly enforced
            return not settings.dj_only_controls

        # User holds the DJ role
        return any(role.id == settings.dj_role_id for role in member.roles)

    @classmethod
    async def require_playback_control(
        cls,
        interaction: discord.Interaction,
        db_manager: MongoManager
    ) -> None:
        """Enforce both voice channel matching and DJ permissions."""
        cls.ensure_user_in_voice(interaction)
        cls.ensure_same_voice_channel(interaction)

        settings = await db_manager.get_guild_settings(interaction.guild_id)
        if settings.dj_only_controls:
            has_permission = await cls.is_dj_or_admin(interaction, db_manager)
            if not has_permission:
                raise PermissionDeniedError(
                    "DJ mode is active. You need the DJ role or Administrator permissions to control music."
                )
