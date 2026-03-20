# Telethon Userbot Adapter

A Telegram Userbot adapter for AstrBot built on top of Telethon.

> Important: use this plugin together with AstrBot's session whitelist. Without a whitelist, the adapter may reply to other bots and create message loops.

中文说明: [README.md](README.md)

## Features

- Receive Telegram messages with a user account and send text or image messages back
- Connect through a real Telegram user account, so uploads are not limited by the Bot API (non-self-hosted) 50 MB upload cap
- Automatically split long messages to fit Telegram limits
- Support quoted replies via the `Reply` segment
- Provide `tg profile` to inspect user/group/channel profiles
- Provide `tg status` to inspect current AstrBot runtime status
- Provide `tg sticker` to add a replied image or sticker into your own sticker pack
- Provide `tg prune` / `tg selfprune` / `tg youprune` for batch message deletion
- Support `zh-CN` / `en-US` runtime responses and WebUI configuration text

## Notes

- This is a Userbot solution. Account restrictions or bans are governed by Telegram policy and are your own responsibility.
- `session_string` grants full access to the Telegram account. Store it carefully.
- If `session_string` expires, generate a new one and update the configuration.
- `fast_upload_enabled` is disabled by default. It only applies to local file uploads; when enabled, uploads prefer the Telethon fast upload parallel path. It relies on Telethon private internals and increases concurrent connections and resource usage, so Telethon upgrades, unstable networks, or stricter account risk controls may lead to upload failures, throttling, or behavior changes.
- `telethon_userbot` does not support platform-level streaming display. If AstrBot enables `provider_settings.streaming_response`, set unsupported platforms to "disable streaming response".
- Batch deletion is a high-risk operation. The current implementation keeps conservative limits enabled by default: each `prune` command deletes at most `200` messages at a time; `selfprune` / `youprune` scan at most `1000` recent messages; throttling is applied between each batch of `100` deletions.
- Delete permissions, service message constraints, and `FloodWait` behavior are determined by Telegram and Telethon. Even with correct parameters, deletion may partially succeed or fail because of permissions or rate limits.

## Installation

Place the plugin directory under `AstrBot`'s `data/plugins/` directory:

```text
data/plugins/astrbot_plugin_telethon_adapter/
```

After installation, AstrBot will install dependencies from `requirements.txt` automatically.

The dependency list includes `cryptg` to improve Telethon cryptography performance.

- On common glibc-based distributions, the prebuilt wheel usually installs directly.
- On Alpine Linux and other musl-based distributions, local build tooling is required, including at least `python3-dev`, `musl-dev`, `gcc`, `linux-headers`, `rust`, and `cargo`.

## Generate `session_string`

First, apply for `api_id` and `api_hash` at [my.telegram.org](https://my.telegram.org). If the application page is unavailable, try another egress IP.

`session_string` must be generated through an interactive login flow. Run this under AstrBot's `data/plugins/` directory:

```bash
python3 ./astrbot_plugin_telethon_adapter/scripts/generate_session.py
```

The script will prompt for:

- `api_id`
- `api_hash`
- phone number

Then Telegram will send a login code, and the script will continue asking for:

- Telegram login code
- 2FA password, if enabled
- proxy settings, optional; supports `socks5`, `socks4`, `http`, and `mtproto`

The script prints a `StringSession` at the end. Copy it into AstrBot's `session_string` field.

Note: Telegram often sends the login code to an already logged-in Telegram client session instead of SMS.

## AstrBot Adapter Configuration

Add a new platform adapter in AstrBot and choose `telethon_userbot`, then fill in:

- `api_id`: Telegram API ID as an integer
- `api_hash`: Telegram API Hash
- `session_string`: the generated StringSession
- `language`: adapter instance language, supports `zh-CN` and `en-US`, default `zh-CN`
- `trigger_prefix`: trigger prefix, default `-astr`. This acts as the message entry filter prefix to reduce unrelated logs and downstream AstrBot pipeline calls; in this plugin it can replace a wake word
- `reply_to_self_triggers_command`: whether replying to your own message should trigger command handling, default `false`. Group chats only; when enabled, replying to a message sent by the current Telethon account is also treated as a wake-up trigger
- `download_incoming_media`: whether to download received media, recommended `true`
- `fast_upload_enabled`: whether to enable Telethon fast upload parallel uploading, default `false`. It only applies to local file path uploads; when enabled, the adapter will prefer fast upload and automatically fall back to Telethon's default uploader when conditions are not met
- `telethon_media_group_timeout`: debounce delay for media group aggregation in seconds, default `1.2`
- `telethon_media_group_max_wait`: maximum wait time for media group aggregation in seconds, default `8.0`
- `proxy_type`: proxy type, supports `socks5`, `socks4`, `http`, `mtproto`
- `proxy_host`: proxy server address
- `proxy_port`: proxy server port
- `proxy_username`: optional username for SOCKS or HTTP proxy
- `proxy_password`: optional password for SOCKS or HTTP proxy
- `proxy_secret`: required only for `mtproto` proxy

`language` affects:

- runtime command text such as `tg profile`, `tg status`, `tg sticker`, and `tg prune`

## Extra Commands

`tg profile` usage:

```text
-astr tg profile
-astr tg profile @username
-astr tg profile https://t.me/channel_name
```

Resolution order for `tg profile` targets:

- explicit argument: `@username`, numeric ID, `t.me` / `telegram.me` link, or `me`
- replied message: inspect the sender of the replied message
- current private chat peer
- current group or channel

`tg status` usage:

```text
-astr tg status
```

`tg status` returns:

- host platform
- Python / AstrBot / Telethon / plugin versions
- current Telegram data center
- current adapter ID
- system CPU / memory / swap usage
- current AstrBot process CPU / memory usage
- current process uptime

`tg sticker` usage:

```text
-astr tg sticker my_pack_name
-astr tg sticker
-astr tg sticker 😎
-astr tg sticker my_pack_name 😎
```

`tg sticker` behavior:

- without replying: `tg sticker <pack_name>` sets the default sticker pack name for the current account
- when replying to an image or sticker: `tg sticker` adds that media to the default sticker pack
- when replying with one argument that is not a valid pack name, the argument is treated as a custom emoji, for example `tg sticker 😎`
- when replying with two arguments, use `tg sticker <pack_name> <emoji>` to temporarily target a specific pack and emoji
- regular images are auto-scaled so the longest edge is `512px`, then converted to `webp`
- the default sticker pack name is stored in AstrBot's plugin KV storage and separated by adapter ID for multiple adapter instances

Batch deletion commands:

```text
-astr tg prune 20
-astr tg prune
-astr tg selfprune 20
-astr tg selfprune
-astr tg youprune @username 20
-astr tg youprune 20
```

Batch deletion details:

- `tg prune [count]`: delete recent messages in the current chat; when used as a reply, the count can be omitted and the command deletes messages between the reply anchor and the command; maximum `200` messages per run
- `tg selfprune [count]`: delete only your own messages; reply-anchor mode is supported; scans at most `1000` recent messages
- `tg youprune [target] [count]`: delete only messages from the target user; target supports `@username`, `t.me` links, or replying to a target message; scans at most `1000` recent messages
- `tg prune`, `tg selfprune`, and `tg youprune` all require the command message to reply to another message when the count is omitted
- deleting service messages, deleting other users' messages without permission, or hitting `FloodWait` may result in partial deletion
