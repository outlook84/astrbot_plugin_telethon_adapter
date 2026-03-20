from __future__ import annotations

import asyncio
import html
import platform
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psutil

try:
    from astrbot.core.config import VERSION as ASTRBOT_VERSION
except ImportError:
    ASTRBOT_VERSION = "unknown"

try:
    from ...plugin_info import PLUGIN_VERSION
except ImportError:
    from plugin_info import PLUGIN_VERSION

from ..i18n import format_data_center_label, get_event_language, t

try:
    from telethon import __version__ as TELETHON_VERSION
except ImportError:
    TELETHON_VERSION = "unknown"

CPU_SAMPLE_INTERVAL_SECONDS = 0.3


@dataclass(slots=True)
class StatusSnapshot:
    platform_name: str
    python_version: str
    astrbot_version: str
    telethon_version: str
    plugin_version: str
    adapter_id: str
    data_center: str
    run_time: str
    system_cpu_percent: str
    system_ram_percent: str
    swap_percent: str
    process_cpu_percent: str
    process_ram_percent: str


class TelethonStatusService:
    def __init__(self, context: Any | None = None) -> None:
        self._context = context

    async def build_status_text(self, event: Any | None = None) -> str:
        snapshot = await self.get_status(event)
        language = get_event_language(event)
        lines = [
            f"<b>{html.escape(t(language, 'status.title'))}</b>",
            f"{html.escape(t(language, 'status.platform'))}: <code>{html.escape(snapshot.platform_name)}</code>",
            f"{html.escape(t(language, 'status.python_version'))}: <code>{html.escape(snapshot.python_version)}</code>",
            f"{html.escape(t(language, 'status.astrbot_version'))}: <code>{html.escape(snapshot.astrbot_version)}</code>",
            f"{html.escape(t(language, 'status.telethon_version'))}: <code>{html.escape(snapshot.telethon_version)}</code>",
            f"{html.escape(t(language, 'status.data_center'))}: <code>{html.escape(snapshot.data_center)}</code>",
            f"{html.escape(t(language, 'status.plugin_version'))}: <code>{html.escape(snapshot.plugin_version)}</code>",
            f"{html.escape(t(language, 'status.adapter_id'))}: <code>{html.escape(snapshot.adapter_id)}</code>",
            f"{html.escape(t(language, 'status.system_cpu'))}: <code>{html.escape(snapshot.system_cpu_percent)}</code>",
            f"{html.escape(t(language, 'status.system_ram'))}: <code>{html.escape(snapshot.system_ram_percent)}</code>",
            f"{html.escape(t(language, 'status.swap'))}: <code>{html.escape(snapshot.swap_percent)}</code>",
            f"{html.escape(t(language, 'status.process_cpu'))}: <code>{html.escape(snapshot.process_cpu_percent)}</code>",
            f"{html.escape(t(language, 'status.process_ram'))}: <code>{html.escape(snapshot.process_ram_percent)}</code>",
            f"{html.escape(t(language, 'status.run_time'))}: <code>{html.escape(snapshot.run_time)}</code>",
        ]
        return "\n".join(lines)

    async def get_status(self, event: Any | None = None) -> StatusSnapshot:
        process = psutil.Process()
        started_at = datetime.fromtimestamp(process.create_time(), tz=timezone.utc)
        uptime_seconds = max(
            0,
            int((datetime.now(timezone.utc) - started_at).total_seconds()),
        )

        psutil.cpu_percent()
        process_cpu_time_before = self._get_process_cpu_time(process)
        monotonic_before = time.monotonic()
        await asyncio.sleep(CPU_SAMPLE_INTERVAL_SECONDS)

        cpu_percent = psutil.cpu_percent()
        cpu_count = psutil.cpu_count(logical=True) or 1
        monotonic_after = time.monotonic()
        process_cpu_time_after = self._get_process_cpu_time(process)
        process_cpu_percent = self._calculate_process_cpu_percent(
            process_cpu_time_before,
            process_cpu_time_after,
            monotonic_before,
            monotonic_after,
            cpu_count,
        )
        ram_stat = psutil.virtual_memory()
        swap_stat = psutil.swap_memory()
        process_ram_percent = process.memory_info().rss / ram_stat.total * 100
        adapter_id, data_center = self._get_adapter_status(event)

        return StatusSnapshot(
            platform_name=platform.system().lower() or "unknown",
            python_version=platform.python_version(),
            astrbot_version=ASTRBOT_VERSION,
            telethon_version=TELETHON_VERSION,
            plugin_version=PLUGIN_VERSION,
            adapter_id=adapter_id,
            data_center=data_center,
            run_time=self.human_time_duration(uptime_seconds, get_event_language(event)),
            system_cpu_percent=f"{cpu_percent:.1f}%",
            system_ram_percent=f"{ram_stat.percent:.1f}%",
            swap_percent=f"{swap_stat.percent:.1f}%",
            process_cpu_percent=f"{process_cpu_percent:.1f}%",
            process_ram_percent=f"{process_ram_percent:.1f}%",
        )

    @staticmethod
    def human_time_duration(seconds: int, language: str = "zh-CN") -> str:
        remaining = max(0, int(seconds))
        days, remaining = divmod(remaining, 24 * 60 * 60)
        hours, remaining = divmod(remaining, 60 * 60)
        minutes, _seconds = divmod(remaining, 60)

        if days > 0:
            return t(language, "status.duration.days", days=days, hours=hours, minutes=minutes)
        if hours > 0:
            return t(language, "status.duration.hours", hours=hours, minutes=minutes)
        return t(language, "status.duration.minutes", minutes=minutes)

    @staticmethod
    def _get_process_cpu_time(process: psutil.Process) -> float:
        cpu_times = process.cpu_times()
        return float(getattr(cpu_times, "user", 0.0)) + float(
            getattr(cpu_times, "system", 0.0),
        )

    @staticmethod
    def _calculate_process_cpu_percent(
        cpu_time_before: float,
        cpu_time_after: float,
        monotonic_before: float,
        monotonic_after: float,
        cpu_count: int,
    ) -> float:
        elapsed = max(monotonic_after - monotonic_before, 1e-6)
        cpu_time_delta = max(cpu_time_after - cpu_time_before, 0.0)
        return cpu_time_delta / elapsed / max(cpu_count, 1) * 100

    def _get_adapter_status(self, event: Any | None = None) -> tuple[str, str]:
        adapter_id = self._get_event_adapter_id(event)
        dc_id = self._get_event_dc_id(event)
        language = get_event_language(event)
        data_center = (
            format_data_center_label(dc_id, language)
            if dc_id is not None
            else t(language, "status.unknown")
        )
        return adapter_id, data_center

    @staticmethod
    def _get_event_adapter_id(event: Any | None) -> str:
        platform_meta = getattr(event, "platform_meta", None)
        adapter_id = str(getattr(platform_meta, "id", "") or "").strip()
        if adapter_id:
            return adapter_id
        return t(get_event_language(event), "status.unknown")

    @staticmethod
    def _get_event_dc_id(event: Any | None) -> int | None:
        client = getattr(event, "client", None)
        session = getattr(client, "session", None)
        dc_id = getattr(session, "dc_id", None)
        try:
            return int(dc_id) if dc_id is not None else None
        except (TypeError, ValueError):
            return None
