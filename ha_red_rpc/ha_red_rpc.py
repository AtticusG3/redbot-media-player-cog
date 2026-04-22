"""
Home Assistant / automation RPC for Red-DiscordBot Audio (media).

Requires: ``--rpc`` on the bot process, Audio cog loaded, and a text channel
where the bot may post briefly (a zero-width sentinel message is deleted).

RPC calls use Red's JSON-RPC over WebSocket (``ws://127.0.0.1:<port>/``).
Method names are ``HAREDRPC__<NAME>`` (see each coroutine).
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from copy import copy
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import discord
import lavalink
from lavalink import PlayerNotFound

from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path

log = logging.getLogger("red.cogs.ha_red_rpc")

MAX_COMMAND_LEN = 2000
_NAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9 _().\-\[\]]+")


class HARedRPC(commands.Cog):
    """RPC helpers for Audio: play, pause, queue, playlist start, and more."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self._rpc_methods: List[Any] = [
            self._play,
            self._bumpplay,
            self._enqueue,
            self._pause,
            self._queue,
            self._playlist_list,
            self._playlist_start,
            self._playlist_save_start,
            self._stop,
            self._skip,
            self._previous,
            self._disconnect,
            self._summon,
            self._queue_clear,
            self._shuffle,
            self._repeat,
            self._seek,
            self._volume,
            self._voice_state,
        ]
        for m in self._rpc_methods:
            bot.register_rpc_handler(m)

    def cog_unload(self) -> None:
        for m in self._rpc_methods:
            with contextlib.suppress(Exception):
                self.bot.unregister_rpc_handler(m)

    async def _audio_cog(self) -> Optional[commands.Cog]:
        return self.bot.get_cog("Audio")

    async def _guild_audio_settings(
        self, guild: Optional[discord.Guild]
    ) -> tuple[Optional[bool], Optional[bool], Optional[int]]:
        """shuffle, repeat, volume_percent from Audio config."""
        if guild is None:
            return None, None, None
        audio = self.bot.get_cog("Audio")
        if audio is None:
            return None, None, None
        try:
            shuffle = await audio.config.guild(guild).shuffle()
            repeat = await audio.config.guild(guild).repeat()
            volume = await audio.config.guild(guild).volume()
            return bool(shuffle), bool(repeat), int(volume)
        except Exception:
            log.exception("Failed to read Audio guild settings for HA RPC")
            return None, None, None

    async def _invoke_as_user(
        self,
        guild_id: int,
        channel_id: int,
        actor_user_id: int,
        command_body: str,
    ) -> Dict[str, Any]:
        """
        Run a command string as if ``actor_user_id`` typed ``prefix + command_body`` in ``channel_id``.

        Parameters
        ----------
        guild_id : int
            Discord guild id.
        channel_id : int
            Text channel or thread id for the synthetic command (and embed output).
        actor_user_id : int
            Member whose permissions apply (use guild owner or bot owner for DJ bypass).
        command_body : str
            Text after the prefix, e.g. ``play never gonna give you up`` or ``pause``.
        """
        if len(command_body) > MAX_COMMAND_LEN:
            return {"ok": False, "error": "command_too_long"}

        if not await self._audio_cog():
            return {"ok": False, "error": "audio_cog_not_loaded"}

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return {"ok": False, "error": "guild_not_found"}

        channel = guild.get_channel(channel_id)
        if channel is None:
            return {"ok": False, "error": "channel_not_found"}

        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return {
                "ok": False,
                "error": "channel_not_text",
                "hint": "Use a normal text channel or thread ID, not voice/category/forum parent.",
                "discord_type": type(channel).__name__,
            }

        perms = channel.permissions_for(guild.me)
        if not perms.send_messages or not perms.read_messages:
            return {"ok": False, "error": "bot_missing_channel_permissions"}

        try:
            member = guild.get_member(actor_user_id)
            if member is None:
                member = await guild.fetch_member(actor_user_id)
        except (discord.HTTPException, discord.NotFound):
            return {"ok": False, "error": "member_not_found"}

        prefixes = await self.bot.get_valid_prefixes(guild)
        prefix = prefixes[0] if prefixes else "!"

        sentinel = await channel.send("\u200b")
        try:
            m = copy(sentinel)
            m.author = member
            m.channel = channel
            m.content = f"{prefix}{command_body}"
            for attr in getattr(m, "_CACHED_SLOTS", ()):
                with contextlib.suppress(AttributeError):
                    delattr(m, attr)

            ctx = await self.bot.get_context(m)
            if not ctx.valid:
                return {
                    "ok": False,
                    "error": "invalid_command",
                    "detail": getattr(ctx, "invoked_with", None),
                }

            await self.bot.invoke(ctx)
            if ctx.command_failed:
                return {
                    "ok": False,
                    "error": "command_failed",
                    "detail": command_body,
                    "invoked_with": getattr(ctx, "invoked_with", None),
                }
            return {"ok": True}
        except commands.CommandError as exc:
            log.exception("HA RPC command error")
            return {"ok": False, "error": "command_error", "detail": str(exc)}
        except Exception as exc:
            log.exception("HA RPC invoke failed")
            return {"ok": False, "error": "invoke_failed", "detail": str(exc)}
        finally:
            with contextlib.suppress(discord.HTTPException):
                await sentinel.delete()

    async def _play(
        self,
        guild_id: int,
        channel_id: int,
        query: str,
        actor_user_id: int,
    ) -> Dict[str, Any]:
        """
        Queue a track or search (same as ``[p]play``). For first connect, the
        actor should be in a voice channel; otherwise use guild owner / bot owner
        so DJ checks pass.

        Parameters
        ----------
        guild_id : int
        channel_id : int
        query : str
            Query or URL passed to Audio.
        actor_user_id : int
            Member whose permissions apply.
        """
        if not query or not str(query).strip():
            return {"ok": False, "error": "empty_query"}
        body = f"play {self._quote_arg(query.strip())}"
        return await self._invoke_as_user(guild_id, channel_id, actor_user_id, body)

    async def _enqueue(
        self,
        guild_id: int,
        channel_id: int,
        query: str,
        actor_user_id: int,
    ) -> Dict[str, Any]:
        """
        Add to queue (same behavior as Audio ``[p]play`` for new items).
        """
        return await self._play(guild_id, channel_id, query, actor_user_id)

    async def _bumpplay(
        self,
        guild_id: int,
        channel_id: int,
        query: str,
        actor_user_id: int,
    ) -> Dict[str, Any]:
        """
        Start a track immediately using Audio ``[p]bumpplay``.
        """
        if not query or not str(query).strip():
            return {"ok": False, "error": "empty_query"}
        body = f"bumpplay {self._quote_arg(query.strip())}"
        return await self._invoke_as_user(guild_id, channel_id, actor_user_id, body)

    async def _pause(
        self,
        guild_id: int,
        channel_id: int,
        actor_user_id: int,
    ) -> Dict[str, Any]:
        """
        Pause or resume (same as ``[p]pause``).
        """
        return await self._invoke_as_user(guild_id, channel_id, actor_user_id, "pause")

    async def _stop(
        self,
        guild_id: int,
        channel_id: int,
        actor_user_id: int,
    ) -> Dict[str, Any]:
        """Stop playback and clear queue (``[p]stop``)."""
        return await self._invoke_as_user(guild_id, channel_id, actor_user_id, "stop")

    async def _skip(
        self,
        guild_id: int,
        channel_id: int,
        actor_user_id: int,
    ) -> Dict[str, Any]:
        """Skip current track (``[p]skip``)."""
        return await self._invoke_as_user(guild_id, channel_id, actor_user_id, "skip")

    async def _previous(
        self,
        guild_id: int,
        channel_id: int,
        actor_user_id: int,
    ) -> Dict[str, Any]:
        """Previous track (``[p]prev``)."""
        return await self._invoke_as_user(guild_id, channel_id, actor_user_id, "prev")

    async def _disconnect(
        self,
        guild_id: int,
        channel_id: int,
        actor_user_id: int,
    ) -> Dict[str, Any]:
        """Disconnect from voice (``[p]disconnect``)."""
        return await self._invoke_as_user(
            guild_id, channel_id, actor_user_id, "disconnect"
        )

    async def _summon(
        self,
        guild_id: int,
        channel_id: int,
        actor_user_id: int,
    ) -> Dict[str, Any]:
        """Summon bot to actor's voice channel (``[p]summon``)."""
        return await self._invoke_as_user(guild_id, channel_id, actor_user_id, "summon")

    async def _queue_clear(
        self,
        guild_id: int,
        channel_id: int,
        actor_user_id: int,
    ) -> Dict[str, Any]:
        """Clear queued tracks (``[p]queue clear``)."""
        return await self._invoke_as_user(
            guild_id, channel_id, actor_user_id, "queue clear"
        )

    async def _shuffle(
        self,
        guild_id: int,
        channel_id: int,
        actor_user_id: int,
    ) -> Dict[str, Any]:
        """Toggle shuffle setting (``[p]shuffle``)."""
        return await self._invoke_as_user(guild_id, channel_id, actor_user_id, "shuffle")

    async def _repeat(
        self,
        guild_id: int,
        channel_id: int,
        actor_user_id: int,
    ) -> Dict[str, Any]:
        """Toggle repeat (``[p]repeat``)."""
        return await self._invoke_as_user(guild_id, channel_id, actor_user_id, "repeat")

    async def _volume(
        self,
        guild_id: int,
        channel_id: int,
        actor_user_id: int,
        volume: int,
    ) -> Dict[str, Any]:
        """Set volume percent (``[p]volume``)."""
        try:
            vol = int(volume)
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid_volume"}
        vol = max(0, min(vol, 150))
        return await self._invoke_as_user(
            guild_id, channel_id, actor_user_id, f"volume {vol}"
        )

    async def _seek(
        self,
        guild_id: int,
        channel_id: int,
        actor_user_id: int,
        position_seconds: Any,
    ) -> Dict[str, Any]:
        """Seek relative to current position (``[p]seek <+/-seconds>``)."""
        try:
            seconds = int(float(position_seconds))
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid_seek_position"}
        return await self._invoke_as_user(
            guild_id, channel_id, actor_user_id, f"seek {seconds}"
        )

    async def _voice_state(
        self,
        guild_id: int,
        self_mute: Any,
        self_deaf: Any,
    ) -> Dict[str, Any]:
        """
        Set the bot's own Discord voice mute/deafen state (not Lavalink volume).

        Parameters
        ----------
        guild_id : int
        self_mute : bool
        self_deaf : bool
        """
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return {"ok": False, "error": "guild_not_found"}
        vs = guild.me.voice
        if vs is None or vs.channel is None:
            return {"ok": False, "error": "bot_not_in_voice"}
        try:
            await guild.change_voice_state(
                channel=vs.channel,
                self_mute=bool(self_mute),
                self_deaf=bool(self_deaf),
            )
            return {"ok": True}
        except discord.HTTPException as exc:
            return {"ok": False, "error": "discord_http", "detail": str(exc)}

    async def _queue(self, guild_id: int) -> Dict[str, Any]:
        """
        Return the current queue, now playing, guild/voice context, and settings.

        Parameters
        ----------
        guild_id : int
        """
        if not await self._audio_cog():
            return {"ok": False, "error": "audio_cog_not_loaded"}

        guild = self.bot.get_guild(guild_id)
        shuffle_v: Optional[bool] = None
        repeat_v: Optional[bool] = None
        volume_pct: Optional[int] = None
        bot_self_mute: Optional[bool] = None
        bot_self_deaf: Optional[bool] = None
        guild_name: Optional[str] = None
        if guild is not None:
            guild_name = guild.name
            shuffle_v, repeat_v, volume_pct = await self._guild_audio_settings(guild)
            me = guild.me
            if me is not None and me.voice is not None:
                bot_self_mute = me.voice.self_mute
                bot_self_deaf = me.voice.self_deaf

        def track_dict(t: Any) -> Dict[str, Any]:
            return {
                "title": getattr(t, "title", ""),
                "uri": getattr(t, "uri", ""),
                "author": str(getattr(t, "author", "")),
                "length": getattr(t, "length", 0),
            }

        voice_channel_name: Optional[str] = None
        voice_channel_id: Optional[int] = None

        try:
            player = lavalink.get_player(guild_id)
        except (PlayerNotFound, KeyError):
            return {
                "ok": True,
                "paused": False,
                "now_playing": None,
                "queue": [],
                "guild_name": guild_name,
                "voice_channel_name": None,
                "voice_channel_id": None,
                "shuffle": shuffle_v,
                "repeat": repeat_v,
                "volume_percent": volume_pct,
                "bot_self_mute": bot_self_mute,
                "bot_self_deaf": bot_self_deaf,
            }

        ch = getattr(player, "channel", None)
        if ch is not None:
            voice_channel_id = ch.id
            voice_channel_name = getattr(ch, "name", None)

        out: Dict[str, Any] = {
            "ok": True,
            "paused": player.paused,
            "now_playing": None,
            "queue": [],
            "position_ms": getattr(player, "position", None),
            "guild_name": guild_name,
            "voice_channel_name": voice_channel_name,
            "voice_channel_id": voice_channel_id,
            "shuffle": shuffle_v,
            "repeat": repeat_v,
            "volume_percent": volume_pct,
            "bot_self_mute": bot_self_mute,
            "bot_self_deaf": bot_self_deaf,
        }
        if player.current:
            out["now_playing"] = track_dict(player.current)
        for t in player.queue:
            out["queue"].append(track_dict(t))
        return out

    @staticmethod
    def _quote_arg(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    @staticmethod
    def _sanitize_playlist_name(raw_name: str) -> str:
        cleaned = _NAME_SANITIZE_RE.sub(" ", raw_name).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if not cleaned:
            return "Imported Playlist"
        return cleaned[:100]

    @staticmethod
    def _name_with_suffix(base: str, suffix_index: int) -> str:
        if suffix_index <= 1:
            return base
        return f"{base} ({suffix_index})"

    @staticmethod
    def _base_name_from_url(url_text: str) -> str:
        parsed = urlparse(url_text)
        host = parsed.netloc.lower()
        query = parse_qs(parsed.query)
        if "youtube.com" in host or "youtu.be" in host:
            list_id = (query.get("list") or [""])[0].strip()
            if list_id:
                return f"YouTube {list_id}"
            return "YouTube Playlist"
        if "spotify.com" in host:
            path_bits = [p for p in parsed.path.split("/") if p]
            if len(path_bits) >= 2 and path_bits[0] in {"playlist", "album"}:
                source_type = path_bits[0].capitalize()
                source_id = path_bits[1]
                return f"Spotify {source_type} {source_id}"
            return "Spotify Playlist"
        for key in ("name", "title"):
            val = (query.get(key) or [""])[0].strip()
            if val:
                return val
        return "Imported Playlist"

    async def _invoke_or_error(
        self,
        guild_id: int,
        channel_id: int,
        actor_user_id: int,
        command_body: str,
    ) -> Dict[str, Any]:
        result = await self._invoke_as_user(guild_id, channel_id, actor_user_id, command_body)
        if not result.get("ok", False):
            return result
        return {"ok": True}

    async def _save_playlist_guild(
        self,
        guild_id: int,
        channel_id: int,
        actor_user_id: int,
        playlist_name: str,
        playlist_url: str,
    ) -> Dict[str, Any]:
        name_q = self._quote_arg(playlist_name)
        url_q = self._quote_arg(playlist_url)
        command_variants = (
            f"playlist save guild {name_q} {url_q}",
            f"playlist save {name_q} {url_q}",
        )
        last_error: Dict[str, Any] | None = None
        for body in command_variants:
            result = await self._invoke_as_user(guild_id, channel_id, actor_user_id, body)
            if result.get("ok", False):
                return {"ok": True}
            last_error = result
        return last_error or {"ok": False, "error": "playlist_save_failed"}

    async def _playlist_start(
        self,
        guild_id: int,
        channel_id: int,
        playlist_name: str,
        actor_user_id: int,
    ) -> Dict[str, Any]:
        """
        Load a saved Audio playlist (same as ``[p]playlist start``).

        Parameters
        ----------
        guild_id : int
        channel_id : int
        playlist_name : str
            Name or id (spaces allowed).
        actor_user_id : int
        """
        if not playlist_name or not playlist_name.strip():
            return {"ok": False, "error": "empty_playlist_name"}
        name = playlist_name.strip()
        if '"' in name:
            return {"ok": False, "error": "invalid_playlist_name"}
        if " " in name:
            body = f'playlist start "{name}"'
        else:
            body = f"playlist start {name}"
        return await self._invoke_as_user(guild_id, channel_id, actor_user_id, body)

    async def _playlist_save_start(
        self,
        guild_id: int,
        channel_id: int,
        playlist_url: str,
        actor_user_id: int,
    ) -> Dict[str, Any]:
        """
        Save a playlist URL to guild playlists and start playback immediately.

        Attempts source-based naming from URL hints, then applies ``(n)`` suffixes
        when a guild playlist of the same name already exists.
        """
        if not playlist_url or not str(playlist_url).strip():
            return {"ok": False, "error": "empty_playlist_url"}
        source_url = str(playlist_url).strip()
        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {"ok": False, "error": "invalid_playlist_url", "detail": source_url}

        inventory = await self._playlist_list(guild_id, actor_user_id)
        existing_names: set[str] = set()
        if inventory.get("ok", False):
            for entry in inventory.get("playlists", []):
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("scope", "")).strip().lower() != "guild":
                    continue
                name = str(entry.get("name", "")).strip().lower()
                if name:
                    existing_names.add(name)

        base_name = self._sanitize_playlist_name(self._base_name_from_url(source_url))
        pick_index = 1
        candidate_name = base_name
        while candidate_name.lower() in existing_names:
            pick_index += 1
            candidate_name = self._name_with_suffix(base_name, pick_index)

        save_result = await self._save_playlist_guild(
            guild_id,
            channel_id,
            actor_user_id,
            candidate_name,
            source_url,
        )
        if not save_result.get("ok", False):
            return save_result

        stop_result = await self._invoke_or_error(
            guild_id, channel_id, actor_user_id, "stop"
        )
        if not stop_result.get("ok", False):
            return stop_result

        start_result = await self._playlist_start(
            guild_id, channel_id, candidate_name, actor_user_id
        )
        if not start_result.get("ok", False):
            return start_result

        return {
            "ok": True,
            "saved_name": candidate_name,
            "source_url": source_url,
            "started": True,
        }

    async def _playlist_list(self, guild_id: int, actor_user_id: int) -> Dict[str, Any]:
        """
        Return saved playlist names in a machine-readable shape.

        Parameters
        ----------
        guild_id : int
        actor_user_id : int
            Currently unused; reserved for future permission-aware scoping.
        """
        if not await self._audio_cog():
            return {"ok": False, "error": "audio_cog_not_loaded", "playlists": []}

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return {"ok": False, "error": "guild_not_found", "playlists": []}

        audio = self.bot.get_cog("Audio")
        if audio is None:
            return {"ok": False, "error": "audio_cog_not_loaded", "playlists": []}

        playlists: list[dict[str, str]] = []
        seen: set[str] = set()

        def _norm_scope(value: Any, fallback: str) -> str:
            text = str(value).strip().lower() if value is not None else ""
            if not text:
                return fallback
            if "guild" in text:
                return "guild"
            if "user" in text:
                return "user"
            if "global" in text:
                return "global"
            return text

        def _add_playlist(name: str, scope: str, pid: str) -> None:
            n = str(name).strip()
            if not n:
                return
            sid = str(pid).strip() or n
            scope_n = _norm_scope(scope, "unknown")
            skey = f"{scope_n}:{sid}"
            if skey in seen:
                return
            seen.add(skey)
            playlists.append({"name": n, "scope": scope_n, "id": sid})

        def _to_rows(items: Any, default_scope: str) -> int:
            if not isinstance(items, list):
                return 0
            before = len(playlists)
            for row in items:
                if isinstance(row, str):
                    _add_playlist(row, default_scope, row)
                    continue
                if isinstance(row, dict):
                    name = str(
                        row.get("name") or row.get("playlist_name") or row.get("title") or ""
                    )
                    scope = _norm_scope(row.get("scope"), default_scope)
                    pid = str(
                        row.get("id")
                        or row.get("playlist_id")
                        or row.get("identifier")
                        or row.get("uuid")
                        or name
                    )
                    _add_playlist(name, scope, pid)
                    continue
                name = str(
                    getattr(row, "name", None)
                    or getattr(row, "playlist_name", None)
                    or getattr(row, "title", None)
                    or ""
                )
                scope = _norm_scope(getattr(row, "scope", None), default_scope)
                pid = str(
                    getattr(row, "id", None)
                    or getattr(row, "playlist_id", None)
                    or getattr(row, "identifier", None)
                    or getattr(row, "uuid", None)
                    or name
                )
                _add_playlist(name, scope, pid)
            return len(playlists) - before

        # Preferred path: mirror Red Audio `playlist list` backend exactly.
        try:
            from redbot.cogs.audio.apis.playlist_interface import get_all_playlist
            from redbot.cogs.audio.utils import PlaylistScope

            author = guild.get_member(actor_user_id) or self.bot.get_user(actor_user_id)
            if author is None:
                author = guild.owner or guild.me
            specified_user = False

            global_rows = await get_all_playlist(
                scope=PlaylistScope.GLOBAL.value,
                bot=self.bot,
                guild=guild,
                author=author,
                specified_user=specified_user,
                playlist_api=getattr(audio, "playlist_api", None),
            )
            guild_rows = await get_all_playlist(
                scope=PlaylistScope.GUILD.value,
                bot=self.bot,
                guild=guild,
                author=author,
                specified_user=specified_user,
                playlist_api=getattr(audio, "playlist_api", None),
            )
            user_rows = await get_all_playlist(
                scope=PlaylistScope.USER.value,
                bot=self.bot,
                guild=guild,
                author=author,
                specified_user=specified_user,
                playlist_api=getattr(audio, "playlist_api", None),
            )
            added = 0
            added += _to_rows(global_rows, "global")
            added += _to_rows(guild_rows, "guild")
            added += _to_rows(user_rows, "user")
            log.debug(
                "Playlist backend get_all_playlist added=%s totals: global=%s guild=%s user=%s",
                added,
                len(global_rows) if isinstance(global_rows, list) else "na",
                len(guild_rows) if isinstance(guild_rows, list) else "na",
                len(user_rows) if isinstance(user_rows, list) else "na",
            )
        except Exception:
            log.debug(
                "Playlist backend get_all_playlist unavailable; using fallback paths",
                exc_info=True,
            )

        def _parse_rows(rows: Any, default_scope: str) -> int:
            if isinstance(rows, dict):
                rows = (
                    rows.get("playlists")
                    or rows.get("items")
                    or rows.get("data")
                    or rows.get("results")
                    or []
                )
            if isinstance(rows, (set, tuple)):
                rows = list(rows)
            if not isinstance(rows, list):
                return 0
            before = len(playlists)
            for row in rows:
                if isinstance(row, str):
                    _add_playlist(row, default_scope, row)
                    continue
                name = ""
                scope = default_scope
                pid = ""
                if isinstance(row, dict):
                    name = str(
                        row.get("name") or row.get("playlist_name") or row.get("title") or ""
                    )
                    scope = _norm_scope(row.get("scope"), default_scope)
                    pid = str(
                        row.get("id")
                        or row.get("playlist_id")
                        or row.get("identifier")
                        or row.get("uuid")
                        or name
                    )
                else:
                    name = str(
                        getattr(row, "name", None)
                        or getattr(row, "playlist_name", None)
                        or getattr(row, "title", None)
                        or ""
                    )
                    scope = _norm_scope(getattr(row, "scope", None), default_scope)
                    pid = str(
                        getattr(row, "id", None)
                        or getattr(row, "playlist_id", None)
                        or getattr(row, "identifier", None)
                        or getattr(row, "uuid", None)
                        or name
                    )
                _add_playlist(name, scope, pid)
            return len(playlists) - before

        async def _try_method(api_obj: Any, api_name: str, meth_name: str) -> int:
            meth = getattr(api_obj, meth_name, None)
            if meth is None:
                return 0
            if not callable(meth):
                return 0
            default_scope = (
                "global"
                if "global" in meth_name
                else "user"
                if "user" in meth_name
                else "guild"
            )
            arg_variants: list[tuple[Any, ...]] = [
                (guild_id,),
                (guild,),
                (actor_user_id,),
                (member,),
                (guild_id, actor_user_id),
                (guild, member),
                tuple(),
            ]
            for args in arg_variants:
                try:
                    rows = await meth(*args)
                except TypeError:
                    continue
                except Exception:
                    log.debug(
                        "Playlist API call failed: %s.%s args=%s",
                        api_name,
                        meth_name,
                        args,
                        exc_info=True,
                    )
                    continue
                added = _parse_rows(rows, default_scope)
                log.debug(
                    "Playlist API call ok: %s.%s args=%s added=%s total=%s",
                    api_name,
                    meth_name,
                    args,
                    added,
                    len(playlists),
                )
                return added
            return 0

        if not playlists:
            try:
                api_candidates: list[tuple[str, Any]] = [
                    ("playlist_api", getattr(audio, "playlist_api", None)),
                    ("playlist_manager", getattr(audio, "playlist_manager", None)),
                    ("playlists", getattr(audio, "playlists", None)),
                    ("playlist_interface", getattr(audio, "playlist_interface", None)),
                    ("playlist_cache", getattr(audio, "playlist_cache", None)),
                ]
                method_names = (
                    "get_all_playlist_for_guild",
                    "get_all_playlists_for_guild",
                    "get_all_playlist_for_user",
                    "get_all_playlists_for_user",
                    "get_all_global_playlist",
                    "get_all_global_playlists",
                    "get_all_playlist",
                    "get_all_playlists",
                    "all_playlist",
                    "all_playlists",
                    "list_playlists",
                )
                for api_name, api_obj in api_candidates:
                    if api_obj is None:
                        log.debug("Playlist API missing: audio.%s", api_name)
                        continue
                    try:
                        available = sorted(
                            n
                            for n in dir(api_obj)
                            if "playlist" in n.lower() and callable(getattr(api_obj, n, None))
                        )
                    except Exception:
                        available = []
                    log.debug(
                        "Playlist API candidate: audio.%s type=%s methods=%s",
                        api_name,
                        type(api_obj).__name__,
                        available[:25],
                    )
                    for meth_name in method_names:
                        await _try_method(api_obj, api_name, meth_name)
            except Exception:
                log.exception("HA RPC playlist inventory read failed")
                return {"ok": False, "error": "playlist_inventory_failed", "playlists": []}

        def _extract_names(
            node: Any,
            fallback_scope: str,
            out: list[tuple[str, str, str]],
            *,
            in_playlist_context: bool = False,
        ) -> None:
            if isinstance(node, dict):
                lowered_keys = [str(k).lower() for k in node.keys()]
                ctx = in_playlist_context or any("playlist" in k for k in lowered_keys)
                name = node.get("name") or node.get("playlist_name") or node.get("title")
                looks_like_playlist = (
                    ctx
                    or "playlist_id" in node
                    or "tracks" in node
                    or "track_count" in node
                )
                if looks_like_playlist and isinstance(name, str) and name.strip():
                    scope = _norm_scope(node.get("scope"), fallback_scope)
                    pid = str(
                        node.get("id")
                        or node.get("playlist_id")
                        or node.get("identifier")
                        or node.get("uuid")
                        or name
                    )
                    out.append((name, scope, pid))
                for key, value in node.items():
                    key_ctx = ctx or ("playlist" in str(key).lower())
                    _extract_names(
                        value,
                        fallback_scope,
                        out,
                        in_playlist_context=key_ctx,
                    )
                return
            if isinstance(node, list):
                for value in node:
                    _extract_names(
                        value,
                        fallback_scope,
                        out,
                        in_playlist_context=in_playlist_context,
                    )

        if not playlists:
            # Last-resort fallback for versions that hide playlist APIs behind command wrappers.
            # We only read Audio cog JSON files and extract playlist-like objects by shape.
            try:
                audio_dir: Path = cog_data_path(raw_name="Audio")
                json_files = [p for p in audio_dir.rglob("*.json")]
                discovered: list[tuple[str, str, str]] = []
                for jf in json_files[:200]:
                    try:
                        payload = json.loads(jf.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    _extract_names(payload, "guild", discovered, in_playlist_context=False)
                for n, s, pid in discovered:
                    _add_playlist(n, s, pid)
                log.debug(
                    "Playlist JSON fallback scanned_files=%s discovered=%s total=%s",
                    len(json_files),
                    len(discovered),
                    len(playlists),
                )
            except Exception:
                log.debug("Playlist JSON fallback failed", exc_info=True)

        if not playlists:
            try:
                audio_level = sorted(
                    n for n in dir(audio) if "playlist" in n.lower() and not n.startswith("_")
                )
            except Exception:
                audio_level = []
            log.debug("Audio-level playlist attrs=%s", audio_level[:40])
        log.debug("HA RPC playlist inventory total=%s", len(playlists))
        return {"ok": True, "playlists": playlists}
