from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PLUGIN_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SLUG_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class RegistryValidationError(ValueError):
    """Raised when plugins.json does not satisfy the registry contract."""


def load_registry(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RegistryValidationError(f"{path} is not valid JSON: {exc.msg}.") from exc


def iter_entries(registry: Any) -> list[dict[str, Any]]:
    if isinstance(registry, list):
        entries = registry
    elif isinstance(registry, dict):
        plugins = registry.get("plugins")
        if isinstance(plugins, dict):
            entries = registry_object_values(plugins)
        else:
            entries = registry_object_values(registry)
    else:
        raise RegistryValidationError("plugins.json must be a JSON array or object.")

    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RegistryValidationError(f"entry #{index + 1} must be an object.")
        normalized.append(entry)
    return normalized


def registry_object_values(registry: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for name, value in registry.items():
        if not isinstance(value, dict):
            raise RegistryValidationError("each plugin entry must be an object.")
        entry = dict(value)
        entry.setdefault("name", name)
        entries.append(entry)
    return entries


def validate_repo(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RegistryValidationError(f"{name}: repo is required.")
    repo = value.strip()
    if repo.endswith(".git"):
        raise RegistryValidationError(f"{name}: repo must not end with .git.")

    if "/" in repo and "://" not in repo:
        parts = repo.split("/")
        if len(parts) == 2 and all(SLUG_PART_RE.fullmatch(part) for part in parts):
            return
        raise RegistryValidationError(f"{name}: repo must be owner/repo or https://github.com/owner/repo.")

    parsed = urlparse(repo)
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        raise RegistryValidationError(f"{name}: repo must be owner/repo or https://github.com/owner/repo.")
    if parsed.query or parsed.fragment:
        raise RegistryValidationError(f"{name}: repo URL must not include query strings or fragments.")
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 2 or not all(SLUG_PART_RE.fullmatch(part) for part in parts):
        raise RegistryValidationError(f"{name}: repo must be owner/repo or https://github.com/owner/repo.")
    if parts[1].endswith(".git"):
        raise RegistryValidationError(f"{name}: repo must not end with .git.")


def require_string(entry: dict[str, Any], field: str, name: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RegistryValidationError(f"{name}: {field} is required and must be a non-empty string.")
    return value.strip()


def validate_entry(entry: dict[str, Any]) -> None:
    name = require_string(entry, "name", "<unknown>")
    if not PLUGIN_NAME_RE.fullmatch(name):
        raise RegistryValidationError(f"{name}: name may only contain letters, numbers, underscore, dash, and dot.")

    require_string(entry, "author", name)
    require_string(entry, "entry", name)
    validate_repo(entry.get("repo"), name)

    description = entry.get("description", entry.get("desc"))
    if not isinstance(description, str) or not description.strip():
        raise RegistryValidationError(f"{name}: description or desc is required.")

    desc = entry.get("desc")
    if desc is not None:
        if not isinstance(desc, str) or not desc.strip():
            raise RegistryValidationError(f"{name}: desc must be a non-empty string when provided.")
        if len(desc) > 70:
            raise RegistryValidationError(f"{name}: desc must be 70 characters or fewer.")

    display_name = entry.get("display_name")
    if display_name is not None and (not isinstance(display_name, str) or not display_name.strip()):
        raise RegistryValidationError(f"{name}: display_name must be a non-empty string when provided.")

    tags = entry.get("tags", [])
    if tags is None:
        return
    if not isinstance(tags, list):
        raise RegistryValidationError(f"{name}: tags must be an array of strings.")
    if len(tags) > 5:
        raise RegistryValidationError(f"{name}: tags must contain at most 5 items.")
    for tag in tags:
        if not isinstance(tag, str) or not tag.strip():
            raise RegistryValidationError(f"{name}: tags must contain non-empty strings only.")


def validate_registry(registry: Any) -> None:
    entries = iter_entries(registry)
    seen: set[str] = set()
    for entry in entries:
        validate_entry(entry)
        name = entry["name"]
        if name in seen:
            raise RegistryValidationError(f"{name}: duplicate plugin name.")
        seen.add(name)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Shinsekai plugin registry JSON.")
    parser.add_argument("plugins_json", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        validate_registry(load_registry(args.plugins_json))
    except RegistryValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"validated {args.plugins_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
