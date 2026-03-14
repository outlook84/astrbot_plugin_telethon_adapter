from __future__ import annotations

from typing import Any


TELETHON_CONFIG_METADATA = {
    "api_id": {
        "description": "Telegram API ID",
        "type": "int",
        "hint": "在 my.telegram.org 申请得到的 API ID。",
    },
    "api_hash": {
        "description": "Telegram API Hash",
        "type": "string",
        "hint": "在 my.telegram.org 申请得到的 API Hash。",
    },
    "session_string": {
        "description": "Telethon StringSession",
        "type": "text",
        "hint": "先通过 scripts/generate_session.py 交互登录，再把输出的 StringSession 填到这里。",
    },
    "id": {
        "description": "适配器 ID",
        "type": "string",
        "hint": "平台实例唯一标识，用于区分多个 Telegram 适配器实例。",
    },
    "trigger_prefix": {
        "description": "触发前缀",
        "type": "string",
        "hint": "仅处理以此前缀开头的消息。留空表示处理所有消息。",
    },
    "ignore_self_messages": {
        "description": "忽略自身发送者消息",
        "type": "bool",
        "hint": "开启后，不处理 sender_id 等于当前账号 ID 的消息。",
    },
    "download_incoming_media": {
        "description": "下载入站媒体",
        "type": "bool",
        "hint": "关闭后，不下载收到的图片、文件、音视频附件。",
    },
    "incoming_media_ttl_seconds": {
        "description": "入站媒体缓存 TTL",
        "type": "float",
        "hint": "媒体下载到本地后保留的秒数。设为 0 或负数表示仅在适配器退出时清理。",
    },
    "log_processed_messages_only": {
        "description": "仅记录已处理消息",
        "type": "bool",
        "hint": "开启后，只记录真正提交给 AstrBot 处理的消息。",
    },
    "telethon_media_group_timeout": {
        "description": "媒体组聚合延迟",
        "type": "float",
        "hint": "媒体组防抖等待时间，单位秒。",
    },
    "telethon_media_group_max_wait": {
        "description": "媒体组最大等待时间",
        "type": "float",
        "hint": "媒体组聚合的最长等待时间，单位秒。",
    },
    "proxy_type": {
        "description": "代理类型",
        "type": "string",
        "hint": "支持 socks5、socks4、http、mtproto。",
        "options": ["", "socks5", "socks4", "http", "mtproto"],
        "labels": ["直连", "SOCKS5", "SOCKS4", "HTTP", "MTProto"],
    },
    "proxy_host": {
        "description": "代理主机",
        "type": "string",
        "hint": "代理服务器地址，例如 127.0.0.1。",
    },
    "proxy_port": {
        "description": "代理端口",
        "type": "int",
        "hint": "代理端口，例如 1080。",
    },
    "proxy_username": {
        "description": "代理用户名",
        "type": "string",
        "hint": "SOCKS/HTTP 代理可选用户名。",
    },
    "proxy_password": {
        "description": "代理密码",
        "type": "string",
        "hint": "SOCKS/HTTP 代理可选密码。",
    },
    "proxy_rdns": {
        "description": "代理远程 DNS",
        "type": "bool",
        "hint": "SOCKS/HTTP 代理是否通过代理端进行域名解析，默认开启。",
        "invisible": True,
    },
    "proxy_secret": {
        "description": "MTProto Secret",
        "type": "string",
        "hint": "仅 MTProto 代理需要填写 secret。",
    },
}

DEFAULT_CONFIG_TEMPLATE = {
    "api_id": 123456,
    "api_hash": "your_api_hash",
    "session_string": "",
    "id": "telethon_userbot",
    "trigger_prefix": "-astr",
    "ignore_self_messages": False,
    "download_incoming_media": True,
    "incoming_media_ttl_seconds": 600.0,
    "log_processed_messages_only": True,
    "telethon_media_group_timeout": 1.2,
    "telethon_media_group_max_wait": 8.0,
    "proxy_type": "",
    "proxy_host": "",
    "proxy_port": 0,
    "proxy_username": "",
    "proxy_password": "",
    "proxy_secret": "",
}


def parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "":
            return default
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def parse_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    normalized = str(value).strip()
    return normalized if normalized else default


def parse_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return default
        try:
            return int(normalized)
        except ValueError:
            return default
    return default


def parse_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return default
        try:
            return float(normalized)
        except ValueError:
            return default
    return default


def normalize_proxy_type(value: Any) -> str:
    proxy_type = parse_str(value, "").lower()
    if proxy_type == "mtproxy":
        return "mtproto"
    return proxy_type


def apply_config(adapter: Any) -> None:
    adapter.api_id = parse_int(adapter.config.get("api_id"), 0)
    adapter.api_hash = parse_str(adapter.config.get("api_hash"), "")
    adapter.session_string = parse_str(adapter.config.get("session_string"), "")
    adapter.trigger_prefix = parse_str(adapter.config.get("trigger_prefix"), "")
    adapter.ignore_self_messages = parse_bool(
        adapter.config.get("ignore_self_messages"), False
    )
    adapter.download_incoming_media = parse_bool(
        adapter.config.get("download_incoming_media"), True
    )
    adapter.incoming_media_ttl_seconds = parse_float(
        adapter.config.get("incoming_media_ttl_seconds"),
        600.0,
    )
    adapter.log_processed_messages_only = parse_bool(
        adapter.config.get("log_processed_messages_only"), True
    )
    adapter.media_group_timeout = parse_float(
        adapter.config.get("telethon_media_group_timeout"),
        1.2,
    )
    adapter.media_group_max_wait = parse_float(
        adapter.config.get("telethon_media_group_max_wait"),
        8.0,
    )
    adapter.proxy_type = normalize_proxy_type(adapter.config.get("proxy_type"))
    adapter.proxy_host = parse_str(adapter.config.get("proxy_host"), "")
    adapter.proxy_port = parse_int(adapter.config.get("proxy_port"), 0)
    adapter.proxy_username = parse_str(adapter.config.get("proxy_username"), "")
    adapter.proxy_password = str(adapter.config.get("proxy_password", "") or "")
    adapter.proxy_rdns = parse_bool(adapter.config.get("proxy_rdns"), True)
    adapter.proxy_secret = parse_str(adapter.config.get("proxy_secret"), "")


def config_error(field_name: str, current_value: Any, suggestion: str) -> ValueError:
    return ValueError(
        f"[Telethon] 配置字段 {field_name} 的当前值为 {current_value!r}。{suggestion}"
    )


def validate_config(adapter: Any) -> None:
    if adapter.api_id <= 0:
        raise config_error(
            "api_id",
            adapter.config.get("api_id"),
            "请填写从 my.telegram.org 获取的正整数 API ID。",
        )
    if not adapter.api_hash:
        raise config_error(
            "api_hash",
            adapter.config.get("api_hash"),
            "请填写从 my.telegram.org 获取的 API Hash。",
        )
    if not adapter.session_string:
        raise config_error(
            "session_string",
            adapter.config.get("session_string"),
            "请先运行 scripts/generate_session.py 生成有效的 StringSession。",
        )

    allowed_proxy_types = {"", "socks5", "socks4", "http", "mtproto"}
    if adapter.proxy_type not in allowed_proxy_types:
        raise config_error(
            "proxy_type",
            adapter.config.get("proxy_type"),
            "请从 '', socks5, socks4, http, mtproto 中选择一个值。",
        )

    if adapter.proxy_type:
        if not adapter.proxy_host:
            raise config_error(
                "proxy_host",
                adapter.config.get("proxy_host"),
                "启用代理时请填写代理主机地址。",
            )
        if adapter.proxy_port <= 0:
            raise config_error(
                "proxy_port",
                adapter.config.get("proxy_port"),
                "启用代理时请填写大于 0 的代理端口。",
            )
        if adapter.proxy_type == "mtproto" and not adapter.proxy_secret:
            raise config_error(
                "proxy_secret",
                adapter.config.get("proxy_secret"),
                "使用 MTProto 代理时请填写 proxy_secret。",
            )

    if adapter.media_group_timeout < 0:
        raise config_error(
            "telethon_media_group_timeout",
            adapter.config.get("telethon_media_group_timeout"),
            "请填写大于等于 0 的秒数。",
        )
    if adapter.media_group_max_wait <= 0:
        raise config_error(
            "telethon_media_group_max_wait",
            adapter.config.get("telethon_media_group_max_wait"),
            "请填写大于 0 的秒数。",
        )
