# Changelog

## 0.5.0 - 2026-03-16

### 新增 / Added

- 增加 `zh-CN` / `en-US` 双语 i18n 资源，覆盖适配器 WebUI 配置文案、运行时回复文本与中英文 README。
- 增加 `reply_to_self_triggers_command` 配置项，默认 `false`。开启后，仅群聊中“回复当前 Telethon 账号自己发出的消息”会被视为一次唤醒，并继续进入命令/消息处理流程。

- Added bilingual `zh-CN` / `en-US` i18n resources covering WebUI configuration text, runtime responses, and Chinese/English READMEs.
- Added the `reply_to_self_triggers_command` option, defaulting to `false`. When enabled, only group-chat replies to messages sent by the current Telethon account are treated as a wake-up trigger and continue into command or message handling.

### 修复 / Fixed

- 补全 thread/session 识别、topic root reply 处理，以及 topic 内发送和引用回复的 thread 透传。
- 加固 `tg prune`、`tg selfprune`、`tg youprune`：增加更严格的全局删除锁与参数校验。
- 修复 `trigger_prefix` 为空时的群聊唤醒行为，避免错误绕过 AstrBot 的群聊唤醒规则。

- Added thread/session detection, topic root reply handling, and thread-aware sending plus quoted replies inside topics.
- Hardened `tg prune`, `tg selfprune`, and `tg youprune`: Add stricter global deletion locking plus argument validation.
- Fixed group wake-up behavior when `trigger_prefix` is empty so group messages no longer bypass AstrBot's own wake-up rules unintentionally.

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
