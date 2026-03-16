# Changelog

## 0.4.0 - 2026-03-15

### 新增 / Added

- 增加 `tg sticker` 命令，支持设置默认贴纸包名，并将回复的图片/贴纸加入自己的贴纸包。

- Added the `tg sticker` command to set a default sticker pack name and add a replied image or sticker to the user's own sticker pack.

## 0.3.0 - 2026-03-15

### 新增 / Added

- 增加 `tg profile`、`tg status`、`tg prune`、`tg selfprune`、`tg youprune` 一组 Telegram 管理命令。
- `tg profile` 用于查询用户、群组或频道资料。
- `tg status` 用于查看当前 AstrBot 运行状态。
- `tg prune` 支持按最近消息或回复锚点批量删除消息；`tg selfprune` 只删除自己的消息；`tg youprune` 只删除指定用户的消息。

- Added a Telegram management command set: `tg profile`, `tg status`, `tg prune`, `tg selfprune`, and `tg youprune`.
- `tg profile` inspects user, group, or channel profiles.
- `tg status` shows the current AstrBot runtime status.
- `tg prune` supports deleting recent messages or messages between a reply anchor and the command; `tg selfprune` deletes only the user's own messages; `tg youprune` deletes only messages from a specified user.

## 0.2.0 - 2026-03-14

### 新增 / Added

- 增加插件元数据：显示名称、支持平台、Logo，以及元数据同步脚本。
- 增加消息 Markdown 到 HTML 的转换能力，并优化 `@` 提及格式化。

- Added plugin metadata, including display name, supported platforms, logo, and a metadata sync script.
- Added Markdown-to-HTML conversion for messages and improved `@` mention formatting.

### 重构 / Refactored

- 移除 `ignore_self_messages` 配置项，简化消息过滤逻辑。如需忽略机器人自身的消息，请前往 `AstrBot` 网页端 `配置文件` 中进行配置。

- Removed the `ignore_self_messages` option to simplify message filtering. To ignore the bot's own messages, configure it in AstrBot's WebUI profile settings.

## 0.1.3 - 2026-03-11

### 新增 / Added

- 为 Telethon 适配器增加代理支持。

- Added proxy support for the Telethon adapter.
