"""
Fast upload support for local Telethon media sending.

This file includes logic adapted from AIOFastTelethonHelper:
https://github.com/aron1cx/AIOFastTelethonHelper

Original upstream license: MIT
Original copyright:
- Copyright (c) 2021 MiyukiKun
- Copyright (c) 2025 Aron1cX
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
from pathlib import Path
from typing import Any

from astrbot.api import logger

try:
    from telethon import helpers, utils
    from telethon.network import MTProtoSender
    from telethon.tl import types
    from telethon.tl.alltlobjects import LAYER
    from telethon.tl.functions import InvokeWithLayerRequest
    from telethon.tl.functions.auth import (
        ExportAuthorizationRequest,
        ImportAuthorizationRequest,
    )
    from telethon.tl.functions.upload import SaveBigFilePartRequest, SaveFilePartRequest
except (ImportError, AttributeError) as exc:
    helpers = None
    utils = None
    MTProtoSender = Any
    types = None
    LAYER = None
    InvokeWithLayerRequest = None
    ExportAuthorizationRequest = None
    ImportAuthorizationRequest = None
    SaveBigFilePartRequest = None
    SaveFilePartRequest = None
    _FAST_UPLOAD_IMPORT_ERROR = exc
else:
    _FAST_UPLOAD_IMPORT_ERROR = None


def _debug_logging_enabled(client: Any) -> bool:
    return bool(getattr(client, "telethon_debug_logging", False))


def should_use_fast_upload(client: Any, file: Any) -> bool:
    if _FAST_UPLOAD_IMPORT_ERROR is not None:
        if _debug_logging_enabled(client):
            logger.info(
                "[Telethon][Debug] fast_upload_unavailable: import_error=%r",
                _FAST_UPLOAD_IMPORT_ERROR,
            )
        return False
    if isinstance(file, Path):
        file = str(file.absolute())
    if not isinstance(file, str) or not os.path.isfile(file):
        return False
    # Fast upload depends on Telethon private client internals and must fail closed
    # when the runtime client does not expose the expected low-level hooks.
    required_attrs = (
        "_call",
        "_get_dc",
        "_connection",
        "_log",
        "session",
    )
    missing_attrs = [attr for attr in required_attrs if not hasattr(client, attr)]
    if missing_attrs:
        if _debug_logging_enabled(client):
            logger.info(
                "[Telethon][Debug] fast_upload_unavailable: missing_client_attrs=%s",
                missing_attrs,
            )
        return False
    session = getattr(client, "session", None)
    enabled = bool(
        session is not None
        and hasattr(session, "dc_id")
        and hasattr(session, "auth_key")
    )
    if not enabled and _debug_logging_enabled(client):
        logger.info(
            "[Telethon][Debug] fast_upload_unavailable: invalid_session=%r",
            session,
        )
    if enabled and _debug_logging_enabled(client):
        logger.info(
            "[Telethon][Debug] fast_upload_available: path=%s",
            file,
        )
    return enabled


if _FAST_UPLOAD_IMPORT_ERROR is None:
    class _UploadSender:
        def __init__(
            self,
            client: Any,
            sender: MTProtoSender,
            file_id: int,
            part_count: int,
            is_large: bool,
            index: int,
            stride: int,
            loop: asyncio.AbstractEventLoop,
        ) -> None:
            self.client = client
            self.sender = sender
            self.loop = loop
            self.previous: asyncio.Task | None = None
            self.stride = stride
            if is_large:
                self.request = SaveBigFilePartRequest(file_id, index, part_count, b"")
            else:
                self.request = SaveFilePartRequest(file_id, index, b"")

        async def enqueue_upload(self, data: bytes) -> None:
            if self.previous is not None:
                await self.previous
            self.previous = self.loop.create_task(self._next(data))

        async def _next(self, data: bytes) -> None:
            self.request.bytes = data
            await self.client._call(self.sender, self.request)
            self.request.file_part += self.stride

        async def disconnect(self) -> None:
            if self.previous is not None:
                await self.previous
            await self.sender.disconnect()


    class _ParallelTransferrer:
        def __init__(self, client: Any, dc_id: int | None = None) -> None:
            self.client = client
            self.loop = getattr(client, "loop", None) or asyncio.get_running_loop()
            self.dc_id = dc_id or self.client.session.dc_id
            self.auth_key = (
                None
                if dc_id and self.client.session.dc_id != dc_id
                else self.client.session.auth_key
            )
            self.senders: list[_UploadSender] | None = None
            self.upload_ticker = 0

        @staticmethod
        def _get_connection_count(file_size: int) -> int:
            if file_size <= 0:
                return 1
            full_size = 100 * 1024 * 1024
            max_count = 20
            if file_size > full_size:
                return max_count
            return max(1, math.ceil((file_size / full_size) * max_count))

        async def _create_sender(self) -> MTProtoSender:
            sender = MTProtoSender(self.auth_key, loggers=self.client._log)
            dc = await self.client._get_dc(self.dc_id)
            await sender.connect(
                self.client._connection(
                    dc.ip_address,
                    dc.port,
                    dc.id,
                    loggers=self.client._log,
                    proxy=getattr(self.client, "_proxy", None),
                )
            )
            if not self.auth_key:
                auth = await self.client(ExportAuthorizationRequest(self.dc_id))
                self.client._init_request.query = ImportAuthorizationRequest(
                    id=auth.id,
                    bytes=auth.bytes,
                )
                await sender.send(
                    InvokeWithLayerRequest(LAYER, self.client._init_request)
                )
                self.auth_key = sender.auth_key
            return sender

        async def init_upload(self, file_id: int, file_size: int) -> tuple[int, int, bool]:
            connection_count = self._get_connection_count(file_size)
            part_size = utils.get_appropriated_part_size(file_size) * 1024
            part_count = (file_size + part_size - 1) // part_size
            is_large = file_size > 10 * 1024 * 1024
            self.senders = [
                _UploadSender(
                    self.client,
                    await self._create_sender(),
                    file_id,
                    part_count,
                    is_large,
                    index,
                    connection_count,
                    self.loop,
                )
                for index in range(connection_count)
            ]
            return part_size, part_count, is_large

        async def upload(self, part: bytes) -> None:
            assert self.senders is not None
            await self.senders[self.upload_ticker].enqueue_upload(part)
            self.upload_ticker = (self.upload_ticker + 1) % len(self.senders)

        async def finish_upload(self) -> None:
            if not self.senders:
                return
            disconnect_results = await asyncio.gather(
                *(sender.disconnect() for sender in self.senders),
                return_exceptions=True,
            )
            for result in disconnect_results:
                if isinstance(result, Exception):
                    logger.warning("[Telethon] Failed to disconnect fast upload sender: %s", result)
            self.senders = None


async def _fast_upload_file(
    client: Any,
    file: str,
    *,
    file_size: int | None = None,
) -> Any:
    if _FAST_UPLOAD_IMPORT_ERROR is not None:
        raise RuntimeError("fast upload is unavailable") from _FAST_UPLOAD_IMPORT_ERROR

    actual_size = file_size if file_size is not None else os.path.getsize(file)
    file_id = helpers.generate_random_long()
    part_size: int
    part_count: int
    is_large: bool
    transferrer = _ParallelTransferrer(client)
    part_size, part_count, is_large = await transferrer.init_upload(file_id, actual_size)
    hash_md5 = hashlib.md5()

    if _debug_logging_enabled(client):
        logger.info(
            "[Telethon][Debug] fast_upload_start: path=%s size=%s",
            file,
            actual_size,
        )

    try:
        with open(file, "rb") as reader:
            while True:
                part = await asyncio.to_thread(reader.read, part_size)
                if not part:
                    break
                if not is_large:
                    hash_md5.update(part)
                await transferrer.upload(part)
    finally:
        await transferrer.finish_upload()

    if is_large:
        return types.InputFileBig(file_id, part_count, os.path.basename(file))
    return types.InputFile(file_id, part_count, os.path.basename(file), hash_md5.hexdigest())


async def build_input_media(
    client: Any,
    file: Any,
    *,
    force_document: bool = False,
    file_size: int | None = None,
    progress_callback: Any = None,
    attributes: list[Any] | None = None,
    thumb: Any = None,
    allow_cache: bool = True,
    voice_note: bool = False,
    video_note: bool = False,
    supports_streaming: bool = False,
    mime_type: str | None = None,
    as_image: bool | None = None,
    ttl: int | None = None,
    nosound_video: bool | None = None,
) -> tuple[Any, Any, Any]:
    file_to_media = getattr(client, "_file_to_media", None)
    if not callable(file_to_media):
        raise RuntimeError("Telethon client does not expose _file_to_media")

    if not should_use_fast_upload(client, file):
        return await file_to_media(
            file,
            force_document=force_document,
            file_size=file_size,
            progress_callback=progress_callback,
            attributes=attributes,
            thumb=thumb,
            allow_cache=allow_cache,
            voice_note=voice_note,
            video_note=video_note,
            supports_streaming=supports_streaming,
            mime_type=mime_type,
            as_image=as_image,
            ttl=ttl,
            nosound_video=nosound_video,
        )

    uploaded_file = await _fast_upload_file(client, str(file), file_size=file_size)
    return await file_to_media(
        uploaded_file,
        force_document=force_document,
        file_size=file_size,
        progress_callback=progress_callback,
        attributes=attributes,
        thumb=thumb,
        allow_cache=False,
        voice_note=voice_note,
        video_note=video_note,
        supports_streaming=supports_streaming,
        mime_type=mime_type,
        as_image=as_image,
        ttl=ttl,
        nosound_video=nosound_video,
    )
