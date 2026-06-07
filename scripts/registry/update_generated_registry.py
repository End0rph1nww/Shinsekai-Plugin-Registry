from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class RegistryUpdateError(ValueError):
    """Raised when generated registry output cannot be produced."""


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise RegistryUpdateError(f"missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    payload_bytes = text.encode("utf-8")
    path.write_bytes(payload_bytes)
    return payload_bytes


def write_json_stdout(payload: Any) -> None:
    sys.stdout.buffer.write((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def normalize_registry(registry: Any) -> list[dict[str, Any]]:
    if isinstance(registry, list):
        entries = registry
    elif isinstance(registry, dict) and isinstance(registry.get("plugins"), dict):
        entries = registry_object_values(registry["plugins"])
    elif isinstance(registry, dict):
        entries = registry_object_values(registry)
    else:
        raise RegistryUpdateError("plugins.json must be an array or object.")
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("name"):
            raise RegistryUpdateError("each plugin entry must be an object with name.")
        normalized.append(entry)
    return normalized


def registry_object_values(registry: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for name, value in registry.items():
        if not isinstance(value, dict):
            raise RegistryUpdateError("each plugin entry must be an object with name.")
        entry = dict(value)
        # Keep AstrBot-style object registries usable when name lives in the key.
        entry.setdefault("name", name)
        entries.append(entry)
    return entries


def by_name(registry: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(entry["name"]): entry for entry in registry}


def detect_changed_plugin_names(old_registry: Any, new_registry: Any) -> list[str]:
    old = by_name(normalize_registry(old_registry))
    new = by_name(normalize_registry(new_registry))
    changed: list[str] = []
    for name in sorted(new):
        if old.get(name) != new[name]:
            changed.append(name)
    return changed


def load_package_results(package_results_dir: Path) -> list[dict[str, Any]]:
    if not package_results_dir.exists():
        return []
    results: list[dict[str, Any]] = []
    for path in sorted(package_results_dir.glob("*.json")):
        result = load_json(path)
        if not isinstance(result, dict) or not result.get("name"):
            raise RegistryUpdateError(f"invalid package result: {path}")
        results.append(result)
    return results


PACKAGE_FIELDS = ("version", "commit_sha", "updated_at", "download_url", "sha256", "size", "package", "sec_scan", "logo")
SOURCE_METADATA_FIELDS = ("display_name", "plugin_id")
REPO_METADATA_FIELDS = ("stars", "stargazers_count", "forks", "forks_count", "repo_updated_at")


def normalize_repo_slug(value: str) -> str:
    repo = value.strip()
    if repo.startswith("https://github.com/"):
        repo = repo.removeprefix("https://github.com/").strip("/")
    if repo.startswith("github.com/"):
        repo = repo.removeprefix("github.com/").strip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    parts = repo.split("/")
    if len(parts) != 2 or not all(parts):
        return ""
    return f"{parts[0]}/{parts[1]}"


def fetch_repo_metadata(repo: str, token: str | None = None) -> dict[str, Any]:
    slug = normalize_repo_slug(repo)
    if not slug:
        return {}
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "shinsekai-plugin-registry-ci"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com/repos/{slug}", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    stars = payload.get("stargazers_count")
    forks = payload.get("forks_count")
    return {
        "stars": stars,
        "stargazers_count": stars,
        "forks": forks,
        "forks_count": forks,
        "repo_updated_at": payload.get("updated_at") or "",
    }


def collect_repo_metadata(registry: Any, token: str | None = None) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for entry in normalize_registry(registry):
        name = str(entry["name"])
        try:
            result = fetch_repo_metadata(str(entry.get("repo") or ""), token)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            print(f"warning: failed to fetch repo metadata for {name}: {exc}", file=sys.stderr)
            continue
        if result:
            metadata[name] = result
    return metadata


def merge_repo_metadata(
    registry: dict[str, dict[str, Any]],
    repo_metadata: dict[str, dict[str, Any]],
    base_registry: Any | None = None,
) -> dict[str, dict[str, Any]]:
    base = by_name(normalize_registry(base_registry)) if base_registry is not None else {}
    generated: dict[str, dict[str, Any]] = {}
    for name, entry in registry.items():
        merged = dict(entry)
        metadata = repo_metadata.get(name) or {}
        if not metadata and name in base:
            metadata = {field: base[name].get(field) for field in REPO_METADATA_FIELDS if field in base[name]}
        stars = metadata.get("stars", metadata.get("stargazers_count"))
        forks = metadata.get("forks", metadata.get("forks_count"))
        if stars is not None:
            merged["stars"] = stars
            merged["stargazers_count"] = stars
        if forks is not None:
            merged["forks"] = forks
            merged["forks_count"] = forks
        if metadata.get("repo_updated_at"):
            merged["repo_updated_at"] = metadata["repo_updated_at"]
        generated[name] = merged
    return generated


def merge_package_results(
    registry: Any,
    package_results: list[dict[str, Any]],
    base_registry: Any | None = None,
) -> dict[str, dict[str, Any]]:
    results = {str(result["name"]): result for result in package_results}
    base = by_name(normalize_registry(base_registry)) if base_registry is not None else {}
    generated: dict[str, dict[str, Any]] = {}
    for entry in normalize_registry(registry):
        merged = dict(entry)
        result = results.get(str(entry["name"]))
        if result:
            for field in PACKAGE_FIELDS:
                if field in result:
                    merged[field] = result[field]
            for field in SOURCE_METADATA_FIELDS:
                if not merged.get(field) and result.get(field):
                    merged[field] = result[field]
        elif str(entry["name"]) in base:
            for field in PACKAGE_FIELDS:
                if field in base[str(entry["name"])]:
                    merged[field] = base[str(entry["name"])][field]
            for field in SOURCE_METADATA_FIELDS:
                if not merged.get(field) and base[str(entry["name"])].get(field):
                    merged[field] = base[str(entry["name"])][field]
        generated[str(merged["name"])] = merged
    return generated


def update_generated_registry(
    *,
    plugins_json: Path,
    package_results_dir: Path,
    output: Path,
    md5_output: Path,
    dry_run: bool,
    plugin_names: list[str] | None = None,
    hydrate_repo_metadata: bool = False,
    github_token: str | None = None,
) -> dict[str, dict[str, Any]]:
    source_registry = load_json(plugins_json)
    registry = normalize_registry(source_registry)
    if plugin_names:
        known = set(by_name(registry))
        missing = [name for name in plugin_names if name not in known]
        if missing:
            raise RegistryUpdateError(f"unknown plugin(s): {', '.join(missing)}")
    base_registry = load_json(output, default=None) if output.exists() else None
    generated = merge_package_results(source_registry, load_package_results(package_results_dir), base_registry)
    if hydrate_repo_metadata:
        generated = merge_repo_metadata(
            generated,
            collect_repo_metadata(source_registry, github_token or os.environ.get("GITHUB_TOKEN")),
            base_registry,
        )
    if dry_run:
        write_json_stdout(generated)
        return generated

    output.parent.mkdir(parents=True, exist_ok=True)
    payload_bytes = write_json(output, generated)
    md5_output.write_bytes((json.dumps({"md5": hashlib.md5(payload_bytes).hexdigest()}, indent=2) + "\n").encode("utf-8"))
    return generated


def git_show_json(ref: str, path: str) -> Any:
    completed = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def parse_plugin_names(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate plugin_cache_original.json and plugins-md5.json.")
    parser.add_argument("--plugins-json", type=Path, default=Path("plugins.json"))
    parser.add_argument("--package-results-dir", type=Path, default=Path("package-results"))
    parser.add_argument("--output", type=Path, default=Path("plugin_cache_original.json"))
    parser.add_argument("--md5-output", type=Path, default=Path("plugins-md5.json"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--plugin-name", action="append", default=[])
    parser.add_argument("--plugin-names", default="")
    parser.add_argument("--skip-repo-metadata", action="store_true")
    parser.add_argument("--detect-changed-from")
    parser.add_argument("--selection-output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        plugin_names = list(args.plugin_name) + parse_plugin_names(args.plugin_names)
        if args.detect_changed_from:
            old_registry = git_show_json(args.detect_changed_from, str(args.plugins_json).replace("\\", "/"))
            new_registry = load_json(args.plugins_json)
            plugin_names = detect_changed_plugin_names(old_registry, new_registry)
            if args.selection_output:
                args.selection_output.parent.mkdir(parents=True, exist_ok=True)
                args.selection_output.write_text("\n".join(plugin_names) + ("\n" if plugin_names else ""), encoding="utf-8")
            else:
                print("\n".join(plugin_names))
            return 0

        update_generated_registry(
            plugins_json=args.plugins_json,
            package_results_dir=args.package_results_dir,
            output=args.output,
            md5_output=args.md5_output,
            dry_run=args.dry_run,
            plugin_names=plugin_names,
            hydrate_repo_metadata=not args.skip_repo_metadata,
        )
    except (RegistryUpdateError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
