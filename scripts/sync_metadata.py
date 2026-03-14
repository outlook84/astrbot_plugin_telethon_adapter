from __future__ import annotations

from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin_info import PLUGIN_METADATA


METADATA_PATH = ROOT / "metadata.yaml"


class _PrettyDumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow=flow, indentless=False)


def build_metadata_yaml() -> str:
    payload = {
        "name": PLUGIN_METADATA["name"],
        "desc": PLUGIN_METADATA["desc"],
        "version": PLUGIN_METADATA["version"],
        "author": PLUGIN_METADATA["author"],
        "repo": PLUGIN_METADATA["repo"],
        "display_name": PLUGIN_METADATA["display_name"],
    }
    support_platforms = PLUGIN_METADATA.get("support_platforms", [])
    if support_platforms:
        payload["support_platforms"] = support_platforms
    return yaml.dump(
        payload,
        Dumper=_PrettyDumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def main() -> None:
    content = build_metadata_yaml()
    METADATA_PATH.write_text(content, encoding="utf-8")
    synced_content = METADATA_PATH.read_text(encoding="utf-8")
    if synced_content != content:
        raise RuntimeError(f"Synced metadata content mismatch: {METADATA_PATH}")
    print(f"Synced metadata to {METADATA_PATH}")


if __name__ == "__main__":
    main()
