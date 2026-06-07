from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from pathlib import Path
from typing import Any

try:
    from scripts.registry.package_plugin import PackageError, load_plugins, normalize_repo_slug, resolve_github_ref
    from scripts.registry.update_generated_registry import by_name, load_json, normalize_registry, parse_plugin_names
except ModuleNotFoundError:  # pragma: no cover - supports direct script execution
    from package_plugin import PackageError, load_plugins, normalize_repo_slug, resolve_github_ref
    from update_generated_registry import by_name, load_json, normalize_registry, parse_plugin_names


class SelectionError(ValueError):
    """Raised when stale package selection cannot be completed."""


def _package_url(entry: dict[str, Any]) -> str:
    package = entry.get("package") if isinstance(entry.get("package"), dict) else {}
    return str(package.get("url") or entry.get("download_url") or "").strip()


def select_outdated_plugins(
    *,
    plugins: list[dict[str, Any]],
    generated_registry: Any,
    plugin_names: list[str] | None = None,
    github_token: str | None = None,
) -> list[str]:
    selected: list[str] = []
    generated_by_name = by_name(normalize_registry(generated_registry)) if generated_registry is not None else {}
    requested = set(plugin_names or [])
    if requested:
        known = {str(entry.get("name") or "") for entry in plugins}
        missing = sorted(name for name in requested if name not in known)
        if missing:
            raise SelectionError(f"unknown plugin(s): {', '.join(missing)}")

    for entry in plugins:
        name = str(entry.get("name") or "").strip()
        if not name or (requested and name not in requested):
            continue
        generated = generated_by_name.get(name) or {}
        if not _package_url(generated):
            selected.append(name)
            continue

        owner, repo = normalize_repo_slug(str(entry.get("repo") or ""))
        configured_version = str(entry.get("version") or "").strip() or None
        _version, _ref, current_commit = resolve_github_ref(owner, repo, configured_version, github_token)
        packaged_commit = str(generated.get("commit_sha") or "").strip()
        if not packaged_commit or current_commit != packaged_commit:
            selected.append(name)
    return sorted(set(selected))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select plugins whose packaged commit is missing or stale.")
    parser.add_argument("--plugins-json", type=Path, default=Path("plugins.json"))
    parser.add_argument("--generated-json", type=Path, default=Path("plugin_cache_original.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plugin-name", action="append", default=[])
    parser.add_argument("--plugin-names", default="")
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        plugin_names = list(args.plugin_name) + parse_plugin_names(args.plugin_names)
        generated_registry = load_json(args.generated_json, default={})
        selected = select_outdated_plugins(
            plugins=load_plugins(args.plugins_json),
            generated_registry=generated_registry,
            plugin_names=plugin_names,
            github_token=args.github_token,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n".join(selected) + ("\n" if selected else ""), encoding="utf-8")
        if selected:
            print("Selected stale package plugin(s): " + ", ".join(selected))
    except (SelectionError, PackageError, urllib.error.URLError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
