from astrbot.api.star import Context, Star, register

from .plugin_info import PLUGIN_AUTHOR, PLUGIN_DESC, PLUGIN_NAME, PLUGIN_VERSION
from .telethon_adapter.telethon_adapter import TelethonPlatformAdapter  # noqa: F401


@register(PLUGIN_NAME, PLUGIN_AUTHOR, PLUGIN_DESC, PLUGIN_VERSION)
class TelethonAdapterPlugin(Star):
    def __init__(self, context: Context):
        self.context = context
