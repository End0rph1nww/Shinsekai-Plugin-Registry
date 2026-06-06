from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


class VerificationError(ValueError):
    """Raised when a plugin cannot be marked as verified."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise VerificationError(f"{path} is not valid JSON: {exc.msg}.") from exc


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iter_registry_entries(registry: Any) -> list[tuple[str | None, dict[str, Any]]]:
    if isinstance(registry, list):
        return [(None, entry) for entry in registry if isinstance(entry, dict)]
    if isinstance(registry, dict) and isinstance(registry.get("plugins"), dict):
        return [(key, entry) for key, entry in registry["plugins"].items() if isinstance(entry, dict)]
    if isinstance(registry, dict):
        return [(key, entry) for key, entry in registry.items() if isinstance(entry, dict)]
    raise VerificationError("plugins.json must be a JSON array or object.")


def plugin_entry_name(key: str | None, entry: dict[str, Any]) -> str:
    return str(entry.get("name") or key or "").strip()


def generated_entry(generated_registry: Any, plugin_name: str) -> dict[str, Any]:
    for key, entry in iter_registry_entries(generated_registry):
        if plugin_entry_name(key, entry) == plugin_name:
            return entry
    return {}


def mark_plugin_verified(
    registry: Any,
    *,
    plugin_name: str,
    reviewed_by: str,
    reviewed_at: str,
    reviewed_commit: str,
    reviewed_version: str,
    notes: str,
) -> Any:
    if not plugin_name.strip():
        raise VerificationError("plugin_name is required.")
    if not reviewed_by.strip():
        raise VerificationError("reviewed_by is required.")
    if not reviewed_at.strip():
        raise VerificationError("reviewed_at is required.")
    if not reviewed_commit.strip():
        raise VerificationError("reviewed_commit is required.")
    if not reviewed_version.strip():
        raise VerificationError("reviewed_version is required.")

    found = False
    entries = iter_registry_entries(registry)
    for key, entry in entries:
        if plugin_entry_name(key, entry) != plugin_name:
            continue
        entry["trust_level"] = "verified"
        entry["verified"] = True
        entry["review"] = {
            "status": "maintainer_verified",
            "reviewed_by": reviewed_by.strip(),
            "reviewed_at": reviewed_at.strip(),
            "reviewed_commit": reviewed_commit.strip(),
            "reviewed_version": reviewed_version.strip(),
            "notes": notes.strip(),
        }
        found = True
        break
    if not found:
        raise VerificationError(f"plugin not found: {plugin_name}")
    return registry


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mark one Registry plugin as maintainer verified.")
    parser.add_argument("--plugins-json", type=Path, default=Path("plugins.json"))
    parser.add_argument("--generated-registry", type=Path, default=Path("plugin_cache_original.json"))
    parser.add_argument("--output", type=Path, default=Path("plugins.json"))
    parser.add_argument("--plugin-name", required=True)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--reviewed-at", default=date.today().isoformat())
    parser.add_argument("--reviewed-commit", default="")
    parser.add_argument("--reviewed-version", default="")
    parser.add_argument("--notes", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        registry = load_json(args.plugins_json)
        generated = load_json(args.generated_registry) if args.generated_registry.exists() else {}
        current = generated_entry(generated, args.plugin_name)
        reviewed_commit = args.reviewed_commit or str(current.get("commit_sha") or "")
        reviewed_version = args.reviewed_version or str(current.get("version") or "")
        reviewed_at = args.reviewed_at or datetime.now(UTC).date().isoformat()
        updated = mark_plugin_verified(
            registry,
            plugin_name=args.plugin_name,
            reviewed_by=args.reviewed_by,
            reviewed_at=reviewed_at,
            reviewed_commit=reviewed_commit,
            reviewed_version=reviewed_version,
            notes=args.notes,
        )
        write_json(args.output, updated)
    except VerificationError as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
