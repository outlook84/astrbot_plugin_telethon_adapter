from __future__ import annotations

import asyncio
import html
from dataclasses import dataclass
from datetime import datetime, timezone

import psutil

try:
    from ...plugin_info import PLUGIN_VERSION
except ImportError:
    from plugin_info import PLUGIN_VERSION


@dataclass(slots=True)
class StatusSnapshot:
    version: str
    run_time: str
    cpu_percent: str
    ram_percent: str
    swap_percent: str
    process_cpu_percent: str
    process_ram_percent: str


class TelethonStatusService:
    async def build_status_text(self) -> str:
        snapshot = await self.get_status()
        lines = [
            f"<b>插件版本:</b> {html.escape(snapshot.version)}",
            f"<b>运行时长:</b> {html.escape(snapshot.run_time)}",
            f"<b>系统 CPU:</b> {html.escape(snapshot.cpu_percent)}",
            f"<b>系统内存:</b> {html.escape(snapshot.ram_percent)}",
            f"<b>系统 Swap:</b> {html.escape(snapshot.swap_percent)}",
            f"<b>进程 CPU:</b> {html.escape(snapshot.process_cpu_percent)}",
            f"<b>进程内存:</b> {html.escape(snapshot.process_ram_percent)}",
        ]
        return "\n".join(lines)

    async def get_status(self) -> StatusSnapshot:
        process = psutil.Process()
        started_at = datetime.fromtimestamp(process.create_time(), tz=timezone.utc)
        uptime_seconds = max(
            0,
            int((datetime.now(timezone.utc) - started_at).total_seconds()),
        )

        psutil.cpu_percent()
        process.cpu_percent()
        await asyncio.sleep(0.1)

        cpu_percent = psutil.cpu_percent()
        cpu_count = psutil.cpu_count(logical=True) or 1
        process_cpu_percent = process.cpu_percent() / cpu_count
        ram_stat = psutil.virtual_memory()
        swap_stat = psutil.swap_memory()
        process_ram_percent = process.memory_info().rss / ram_stat.total * 100

        return StatusSnapshot(
            version=PLUGIN_VERSION,
            run_time=self.human_time_duration(uptime_seconds),
            cpu_percent=f"{cpu_percent:.2f}%",
            ram_percent=f"{ram_stat.percent:.2f}%",
            swap_percent=f"{swap_stat.percent:.2f}%",
            process_cpu_percent=f"{process_cpu_percent:.2f}%",
            process_ram_percent=f"{process_ram_percent:.2f}%",
        )

    @staticmethod
    def human_time_duration(seconds: int) -> str:
        remaining = max(0, int(seconds))
        days, remaining = divmod(remaining, 24 * 60 * 60)
        hours, remaining = divmod(remaining, 60 * 60)
        minutes, seconds = divmod(remaining, 60)

        if days > 0:
            return f"{days}天 {hours:02d}小时 {minutes:02d}分钟 {seconds:02d}秒"
        if hours > 0:
            return f"{hours}小时 {minutes:02d}分钟 {seconds:02d}秒"
        if minutes > 0:
            return f"{minutes}分钟 {seconds:02d}秒"
        return f"{seconds}秒"
