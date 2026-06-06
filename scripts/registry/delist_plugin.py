from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class DelistPluginError(ValueError):
    """Raised when a plugin cannot be removed from the registry."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise DelistPluginError(f"{path} is not valid JSON: {exc.msg}.") from exc


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def plugin_entry_name(key: str | None, entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("name") or key or "").strip()
    return str(key or "").strip()


def delist_plugin(registry: Any, *, plugin_name: str) -> Any:
    name = plugin_name.strip()
    if not name:
        raise DelistPluginError("plugin_name is required.")

    if isinstance(registry, list):
        updated = [
            entry
            for entry in registry
            if not (isinstance(entry, dict) and plugin_entry_name(None, entry) == name)
        ]
        if len(updated) == len(registry):
            raise DelistPluginError(f"plugin not found: {name}")
        return updated

    if isinstance(registry, dict):
        plugins = registry.get("plugins")
        if isinstance(plugins, dict):
            delist_plugin_from_object(plugins, name)
            return registry
        delist_plugin_from_object(registry, name)
        return registry

    raise DelistPluginError("plugins.json must be a JSON array or object.")


def delist_plugin_from_object(registry: dict[str, Any], plugin_name: str) -> None:
    for key, entry in list(registry.items()):
        if plugin_entry_name(key, entry) == plugin_name:
            del registry[key]
            return
    raise DelistPluginError(f"plugin not found: {plugin_name}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remove one Registry plugin from plugins.json.")
    parser.add_argument("--plugins-json", type=Path, default=Path("plugins.json"))
    parser.add_argument("--output", type=Path, default=Path("plugins.json"))
    parser.add_argument("--plugin-name", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        registry = load_json(args.plugins_json)
        updated = delist_plugin(registry, plugin_name=args.plugin_name)
        write_json(args.output, updated)
    except DelistPluginError as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
