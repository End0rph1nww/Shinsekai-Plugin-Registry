from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)```", re.IGNORECASE | re.DOTALL)
PLUGIN_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SLUG_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
REQUIRED_FIELDS = ("display_name", "desc", "author", "repo")
OPTIONAL_COPY_FIELDS = ("version", "shinsekai_version")


class SubmissionError(ValueError):
    """Raised when an issue body cannot be converted into a registry entry."""


def extract_json_block(issue_body: str) -> dict[str, Any]:
    match = JSON_BLOCK_RE.search(issue_body)
    if not match:
        raise SubmissionError("Missing fenced ```json block in issue body.")
    raw = match.group(1).strip()
    if not raw:
        raise SubmissionError("The fenced JSON block is empty.")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SubmissionError(f"Malformed JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}.") from exc
    if not isinstance(payload, dict):
        raise SubmissionError("Plugin submission JSON must be an object.")
    return payload


def parse_github_repo_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SubmissionError("repo must be a GitHub URL string.")
    repo_url = value.strip()
    parsed = urlparse(repo_url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        raise SubmissionError("repo must use https://github.com/{owner}/{repo}.")
    if parsed.query or parsed.fragment:
        raise SubmissionError("repo URL must not include query strings or fragments.")
    path = parsed.path.strip("/")
    parts = path.split("/")
    if len(parts) != 2 or not all(SLUG_PART_RE.fullmatch(part) for part in parts):
        raise SubmissionError("repo must use https://github.com/{owner}/{repo}.")
    owner, repo = parts
    if repo.endswith(".git"):
        raise SubmissionError("repo URL must not end with .git.")
    return f"{owner}/{repo}"


def normalize_plugin_name(value: str) -> str:
    name = value.strip().replace("-", "_").lower()
    if not name:
        raise SubmissionError("Plugin name cannot be empty.")
    if not PLUGIN_NAME_RE.fullmatch(name):
        raise SubmissionError("Plugin name may only contain letters, numbers, underscore, dash, and dot.")
    return name


def plugin_name_from_repo(repo_slug: str) -> str:
    return normalize_plugin_name(repo_slug.split("/", 1)[1])


def require_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SubmissionError(f"{field} is required and must be a non-empty string.")
    return value.strip()


def normalize_tags(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise SubmissionError("tags must be an array of strings.")
    if len(value) > 5:
        raise SubmissionError("tags must contain at most 5 items.")
    tags: list[str] = []
    for tag in value:
        if not isinstance(tag, str) or not tag.strip():
            raise SubmissionError("tags must contain non-empty strings only.")
        tags.append(tag.strip())
    return tags


def first_plugin_class(plugin_file: Path) -> str:
    try:
        tree = ast.parse(plugin_file.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return "Plugin"
    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    for name in classes:
        if name.lower().endswith("plugin"):
            return name
    return classes[0] if classes else "Plugin"


def infer_entry_from_source(source_dir: Path, plugin_name: str) -> str:
    candidates = sorted(
        [
            path
            for path in source_dir.rglob("plugin.py")
            if not any(part in {".git", "__pycache__", ".venv", "venv", "node_modules"} for part in path.relative_to(source_dir).parts)
        ],
        key=lambda path: (len(path.relative_to(source_dir).parts), path.as_posix()),
    )
    if not candidates:
        raise SubmissionError("entry is missing and CI could not find plugin.py in the repository.")
    plugin_file = candidates[0]
    class_name = first_plugin_class(plugin_file)
    rel = plugin_file.relative_to(source_dir).with_suffix("")
    module = ".".join(rel.parts)
    if module == "plugin":
        module = f"plugins.{plugin_name.replace('-', '_')}.plugin"
    elif not module.startswith("plugins."):
        module = f"plugins.{module}"
    return f"{module}:{class_name}"


def infer_name_from_entry(entry: str, fallback: str) -> str:
    module = entry.split(":", 1)[0].strip()
    parts = [part for part in module.split(".") if part]
    if len(parts) >= 2 and parts[0] == "plugins":
        return normalize_plugin_name(parts[1])
    return normalize_plugin_name(fallback)


def clone_repo_to_temp(repo_slug: str) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="shinsekai-plugin-submission-"))
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", f"https://github.com/{repo_slug}.git", str(temp_dir)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        detail = (exc.stderr or exc.stdout or "").strip()
        raise SubmissionError(f"could not clone plugin repository for CI metadata inference. {detail}") from exc
    return temp_dir


def build_registry_entry(payload: dict[str, Any]) -> dict[str, Any]:
    for field in REQUIRED_FIELDS:
        require_string(payload, field)

    repo_slug = parse_github_repo_url(payload["repo"])
    desc = require_string(payload, "desc")
    if len(desc) > 200:
        raise SubmissionError("desc must be 200 characters or fewer.")

    repo_name = plugin_name_from_repo(repo_slug)

    source_dir = clone_repo_to_temp(repo_slug)
    try:
        entry_value = infer_entry_from_source(source_dir, repo_name)
        name = infer_name_from_entry(entry_value, repo_name)
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)

    entry = {
        "name": name,
        "display_name": require_string(payload, "display_name"),
        "author": require_string(payload, "author"),
        # Keep owner/repo for compatibility with the existing registry shape.
        "repo": repo_slug,
        "description": desc,
        "desc": desc,
        "entry": entry_value,
    }

    tags = normalize_tags(payload.get("tags"))
    if tags:
        entry["tags"] = tags

    social_link = payload.get("social_link")
    if isinstance(social_link, str) and social_link.strip():
        entry["social_link"] = social_link.strip()
    elif social_link not in (None, ""):
        raise SubmissionError("social_link must be a string when provided.")

    for field in OPTIONAL_COPY_FIELDS:
        if field in payload and payload[field] not in (None, ""):
            entry[field] = payload[field]

    return entry


def load_registry(path: Path) -> Any:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SubmissionError(f"{path} is not valid JSON: {exc.msg}.") from exc


def update_registry(registry: Any, entry: dict[str, Any]) -> Any:
    if isinstance(registry, list):
        next_registry = list(registry)
        for index, existing in enumerate(next_registry):
            if isinstance(existing, dict) and existing.get("name") == entry["name"]:
                next_registry[index] = entry
                break
        else:
            next_registry.append(entry)
        return next_registry

    if isinstance(registry, dict):
        next_registry = dict(registry)
        plugins = next_registry.get("plugins")
        if isinstance(plugins, dict):
            plugins = dict(plugins)
            plugins[entry["name"]] = entry
            next_registry["plugins"] = plugins
            return next_registry
        next_registry[entry["name"]] = entry
        return next_registry

    raise SubmissionError("plugins.json must be a JSON array or object.")


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_summary(path: Path, entry: dict[str, Any]) -> None:
    body = "\n".join(
        [
            f"Plugin submission generated from issue JSON.",
            "",
            f"- Name: `{entry['name']}`",
            f"- Display name: `{entry['display_name']}`",
            f"- Author: `{entry['author']}`",
            f"- Repository: `{entry['repo']}`",
            f"- Entry: `{entry['entry']}`",
            "",
            "This PR was created automatically from a plugin-publish issue. Maintainers should review the repository and entry point before merging.",
            "",
        ]
    )
    path.write_text(body, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse a plugin-publish issue into plugins.json.")
    parser.add_argument("--issue-body-file", required=True, type=Path)
    parser.add_argument("--plugins-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary-file", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        issue_body = args.issue_body_file.read_text(encoding="utf-8")
        entry = build_registry_entry(extract_json_block(issue_body))
        updated = update_registry(load_registry(args.plugins_json), entry)
        write_json(args.output, updated)
        if args.summary_file:
            write_summary(args.summary_file, entry)
    except SubmissionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
