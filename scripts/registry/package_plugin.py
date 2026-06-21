from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from scripts.registry.static_security_scan import scan_directory
except ModuleNotFoundError:  # pragma: no cover - supports direct script execution
    from static_security_scan import scan_directory


DEFAULT_MAX_BYTES = 16_777_216
DEFAULT_MAX_ARCHIVE_BYTES = 67_108_864
DEFAULT_MAX_ARCHIVE_MEMBERS = 10_000
DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 134_217_728
DEFAULT_MAX_LOGO_BYTES = 1_048_576
LOGO_CANDIDATE_NAMES = ("logo.png", "logo.jpg", "logo.jpeg", "logo.webp")
LOGO_CANDIDATE_DIRS = ("", "assets", "asset", "static", "public", "resources", "res", "images", "img")
LOGO_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
EXCLUDED_ANY_DEPTH_DIRS = {
    ".git",
    ".github",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    ".cache",
    "cache",
    "caches",
    "node_modules",
    ".tox",
    "log",
    "logs",
    "tmp",
    "temp",
}
EXCLUDED_TOP_LEVEL_DIRS = {"dist", "build"}
EXCLUDED_DIRS = EXCLUDED_ANY_DEPTH_DIRS | EXCLUDED_TOP_LEVEL_DIRS
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".temp"}
EXCLUDED_FILES = {".DS_Store"}


class PackageError(ValueError):
    """Raised when a plugin cannot be packaged safely."""


PLUGIN_METADATA_PROPERTIES = {
    "plugin_id": "plugin_id",
    "plugin_name": "display_name",
    "plugin_version": "version",
    "plugin_description": "description",
    "plugin_author": "author",
}
PLUGIN_TITLE_CONTRIBUTIONS = {
    "FrontendConfigContribution": ("title",),
    "SettingsUIContribution": ("title", "nav_label"),
    "ToolsTabContribution": ("title",),
}


def normalize_repo_slug(value: str) -> tuple[str, str]:
    repo = value.strip()
    if repo.startswith("https://github.com/"):
        repo = repo.removeprefix("https://github.com/").strip("/")
    parts = repo.split("/")
    if len(parts) != 2 or not all(parts):
        raise PackageError("repo must be owner/repo or https://github.com/owner/repo.")
    if parts[1].endswith(".git"):
        raise PackageError("repo must not end with .git.")
    return parts[0], parts[1]


def version_without_v(version: str) -> str:
    cleaned = (version or "0.0.0").strip()
    return cleaned[1:] if cleaned.lower().startswith("v") else cleaned


def build_r2_key(owner: str, plugin_name: str, version: str, commit_sha: str) -> str:
    clean_version = version_without_v(version)
    commit12 = commit_sha[:12]
    return f"plugins/{owner}/{plugin_name}/{clean_version}/{plugin_name}-{clean_version}-{commit12}.zip"


def build_r2_logo_key(owner: str, plugin_name: str, version: str, commit_sha: str, suffix: str) -> str:
    clean_version = version_without_v(version)
    commit12 = commit_sha[:12]
    clean_suffix = suffix.lower() if suffix.lower() in LOGO_CONTENT_TYPES else ".png"
    return f"assets/{owner}/{plugin_name}/{clean_version}/logo-{commit12}{clean_suffix}"


def should_exclude_parts(rel_parts: tuple[str, ...]) -> bool:
    if any(part in EXCLUDED_ANY_DEPTH_DIRS for part in rel_parts):
        return True
    # Top-level dist/build folders are usually project build artifacts. Nested
    # dist/build folders may be runtime assets, such as plugin frontend pages.
    if rel_parts and rel_parts[0] in EXCLUDED_TOP_LEVEL_DIRS:
        return True
    name = rel_parts[-1] if rel_parts else ""
    if name in EXCLUDED_FILES:
        return True
    if name == ".env" or name.startswith(".env."):
        return True
    if PurePosixPath(name).suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    return False


def should_exclude(path: Path, root: Path) -> bool:
    return should_exclude_parts(path.relative_to(root).parts)


def archive_root_prefix(members: list[zipfile.ZipInfo]) -> str | None:
    roots: set[str] = set()
    for member in members:
        if member.is_dir() or "\\" in member.filename:
            continue
        path = PurePosixPath(member.filename)
        parts = path.parts
        if not parts or path.is_absolute() or ".." in parts:
            continue
        if len(parts) == 1:
            return None
        roots.add(parts[0])
    return next(iter(roots)) if len(roots) == 1 else None


def should_exclude_archive_member(path: PurePosixPath, archive_root: str | None = None) -> bool:
    parts = path.parts
    if archive_root and parts and parts[0] == archive_root:
        parts = parts[1:]
    return should_exclude_parts(tuple(parts))


def candidate_entry_paths(entry: str, plugin_name: str | None = None) -> list[Path]:
    module = entry.split(":", 1)[0].strip()
    if not module:
        raise PackageError("entry must include a module path.")
    parts = [part for part in module.split(".") if part]
    if not parts:
        raise PackageError("entry must include a module path.")

    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(module_parts: list[str]) -> None:
        if not module_parts:
            return
        base = Path(*module_parts)
        for candidate in (base.with_suffix(".py"), base / "__init__.py"):
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)

    add(parts)
    if parts[0] != "plugins":
        add(["plugins", *parts])
    elif len(parts) > 1:
        add(parts[1:])

    # Many legacy Shinsekai plugin repositories are flat: plugin.py sits at the
    # repository root, while the registry entry includes the installed folder name.
    if plugin_name:
        normalized_name = plugin_name.replace("-", "_")
        if parts[0] == normalized_name:
            add(parts[1:])
        if len(parts) > 1 and parts[0] == "plugins" and parts[1] == normalized_name:
            add(parts[2:])
    return candidates


def verify_entry_path(source_dir: Path, entry: str, plugin_name: str | None = None) -> Path:
    for candidate in candidate_entry_paths(entry, plugin_name):
        if (source_dir / candidate).is_file():
            return candidate
    raise PackageError(f"entry module does not exist in cleaned package: {entry}")


def read_python_tree(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        raise PackageError(f"entry module has invalid Python syntax: {path}") from exc


def resolve_string_expr(
    node: ast.AST,
    *,
    local_constants: dict[str, str],
    alias_constants: dict[str, dict[str, str]],
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.strip()
    if isinstance(node, ast.Name):
        return local_constants.get(node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return alias_constants.get(node.value.id, {}).get(node.attr)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = resolve_string_expr(node.left, local_constants=local_constants, alias_constants=alias_constants)
        right = resolve_string_expr(node.right, local_constants=local_constants, alias_constants=alias_constants)
        if left is not None and right is not None:
            return f"{left}{right}".strip()
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return None
            parts.append(value.value)
        return "".join(parts).strip()
    return None


def extract_string_constants(tree: ast.Module) -> dict[str, str]:
    constants: dict[str, str] = {}
    for stmt in tree.body:
        value_node: ast.AST | None = None
        targets: list[ast.AST] = []
        if isinstance(stmt, ast.Assign):
            value_node = stmt.value
            targets = list(stmt.targets)
        elif isinstance(stmt, ast.AnnAssign):
            value_node = stmt.value
            targets = [stmt.target]
        if value_node is None:
            continue
        value = resolve_string_expr(value_node, local_constants=constants, alias_constants={})
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value
    return constants


def module_file_candidates(source_dir: Path, module: str, imported_name: str, plugin_name: str) -> list[Path]:
    parts = [part for part in module.split(".") if part]
    imported = [imported_name] if imported_name else []
    normalized_plugin = plugin_name.replace("-", "_")
    candidates: list[Path] = []

    def add(module_parts: list[str]) -> None:
        if not module_parts:
            return
        base = source_dir.joinpath(*module_parts)
        for candidate in (base.with_suffix(".py"), base / "__init__.py"):
            if candidate not in candidates:
                candidates.append(candidate)

    add([*parts, *imported])
    if not parts:
        add(imported)
    elif len(parts) >= 2 and parts[0] == "plugins" and parts[1] == normalized_plugin:
        add([*parts[2:], *imported])
    elif parts[0] == normalized_plugin:
        add([*parts[1:], *imported])
    return candidates


def load_import_alias_constants(source_dir: Path, tree: ast.Module, plugin_name: str) -> dict[str, dict[str, str]]:
    aliases: dict[str, dict[str, str]] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom):
            module = stmt.module or ""
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname or alias.name
                for candidate in module_file_candidates(source_dir, module, alias.name, plugin_name):
                    if candidate.is_file():
                        aliases[local_name] = extract_string_constants(read_python_tree(candidate))
                        break
        elif isinstance(stmt, ast.Import):
            for alias in stmt.names:
                local_name = alias.asname or alias.name.split(".")[-1]
                for candidate in module_file_candidates(source_dir, alias.name, "", plugin_name):
                    if candidate.is_file():
                        aliases[local_name] = extract_string_constants(read_python_tree(candidate))
                        break
    return aliases


def is_property_method(node: ast.AST) -> bool:
    if not isinstance(node, ast.FunctionDef):
        return False
    return any(isinstance(decorator, ast.Name) and decorator.id == "property" for decorator in node.decorator_list)


def function_return_string(
    node: ast.FunctionDef,
    *,
    local_constants: dict[str, str],
    alias_constants: dict[str, dict[str, str]],
) -> str | None:
    for stmt in node.body:
        if isinstance(stmt, ast.Return) and stmt.value is not None:
            return resolve_string_expr(stmt.value, local_constants=local_constants, alias_constants=alias_constants)
    return None


def class_string_assignments(
    node: ast.ClassDef,
    *,
    local_constants: dict[str, str],
    alias_constants: dict[str, dict[str, str]],
) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in node.body:
        value_node: ast.AST | None = None
        targets: list[ast.AST] = []
        if isinstance(child, ast.Assign):
            value_node = child.value
            targets = list(child.targets)
        elif isinstance(child, ast.AnnAssign):
            value_node = child.value
            targets = [child.target]
        if value_node is None:
            continue
        value = resolve_string_expr(value_node, local_constants=local_constants, alias_constants=alias_constants)
        if not value:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                values[target.id] = value
    return values


def entry_class_name(entry: str) -> str:
    if ":" not in entry:
        return ""
    return entry.split(":", 1)[1].strip().rsplit(".", 1)[-1]


def metadata_class(tree: ast.Module, entry: str) -> ast.ClassDef | None:
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    desired_name = entry_class_name(entry)
    if desired_name:
        for node in classes:
            if node.name == desired_name:
                return node
    for node in classes:
        if node.name.endswith("Plugin"):
            return node
    return classes[0] if len(classes) == 1 else None


def call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def contribution_display_title(
    tree: ast.Module,
    *,
    local_constants: dict[str, str],
    alias_constants: dict[str, dict[str, str]],
) -> str | None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        contribution = PLUGIN_TITLE_CONTRIBUTIONS.get(call_name(node.func))
        if not contribution:
            continue
        for field_name in contribution:
            for keyword in node.keywords:
                if keyword.arg == field_name:
                    value = resolve_string_expr(
                        keyword.value,
                        local_constants=local_constants,
                        alias_constants=alias_constants,
                    )
                    if value:
                        return value
    return None


def infer_source_metadata(source_dir: Path, entry_path: Path, entry: dict[str, Any], plugin_name: str) -> dict[str, str]:
    tree = read_python_tree(source_dir / entry_path)
    local_constants = extract_string_constants(tree)
    alias_constants = load_import_alias_constants(source_dir, tree, plugin_name)
    metadata: dict[str, str] = {}

    cls = metadata_class(tree, str(entry.get("entry") or ""))
    if cls is not None:
        for name, value in class_string_assignments(
            cls,
            local_constants=local_constants,
            alias_constants=alias_constants,
        ).items():
            output_field = PLUGIN_METADATA_PROPERTIES.get(name)
            if output_field and value:
                metadata[output_field] = value
        for child in cls.body:
            if not is_property_method(child):
                continue
            output_field = PLUGIN_METADATA_PROPERTIES.get(child.name)
            if not output_field:
                continue
            value = function_return_string(child, local_constants=local_constants, alias_constants=alias_constants)
            if value:
                metadata[output_field] = value

    if not metadata.get("display_name"):
        title = contribution_display_title(tree, local_constants=local_constants, alias_constants=alias_constants)
        if title:
            metadata["display_name"] = title
    return metadata


def copy_clean_source(source_dir: Path, dest_dir: Path) -> None:
    for path in source_dir.rglob("*"):
        if should_exclude(path, source_dir):
            continue
        rel = path.relative_to(source_dir)
        target = dest_dir / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def build_zip(source_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(source_dir).as_posix()
            posix = PurePosixPath(rel)
            if posix.is_absolute() or ".." in posix.parts:
                raise PackageError(f"unsafe archive path: {rel}")
            archive.write(path, rel)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_logo_file(source_dir: Path) -> Path | None:
    for dirname in LOGO_CANDIDATE_DIRS:
        base = source_dir / dirname if dirname else source_dir
        for filename in LOGO_CANDIDATE_NAMES:
            candidate = base / filename
            if candidate.is_file() and candidate.suffix.lower() in LOGO_CONTENT_TYPES:
                return candidate
    return None


def package_local_plugin(
    *,
    source_dir: Path,
    entry: dict[str, Any],
    output_dir: Path,
    commit_sha: str,
    public_base_url: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
    updated_at: str | None = None,
    fallback_version: str | None = None,
) -> dict[str, Any]:
    name = str(entry.get("name") or "").strip()
    if not name:
        raise PackageError("plugin entry is missing name.")
    owner, _repo = normalize_repo_slug(str(entry.get("repo") or ""))

    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{name}-clean-") as temp:
        clean_dir = Path(temp) / name
        clean_dir.mkdir(parents=True, exist_ok=True)
        copy_clean_source(source_dir, clean_dir)
        entry_path = verify_entry_path(clean_dir, str(entry.get("entry") or ""), name)
        source_metadata = infer_source_metadata(clean_dir, entry_path, entry, name)
        version = (
            source_metadata.get("version", "").strip()
            or str(entry.get("version") or "").strip()
            or str(fallback_version or "").strip()
            or "v0.0.0"
        )

        scan = scan_directory(clean_dir)
        if not scan["pass"]:
            raise PackageError(f"static security scan failed: {scan['msg']}")
        print(f"Static security scan passed for {name}: {scan['msg']}")

        r2_key = build_r2_key(owner, name, version, commit_sha)
        zip_path = output_dir / Path(r2_key).name
        build_zip(clean_dir, zip_path)
        logo_path = find_logo_file(clean_dir)
        logo_asset = None
        logo_url = ""
        if logo_path:
            logo_size = logo_path.stat().st_size
            if logo_size > DEFAULT_MAX_LOGO_BYTES:
                raise PackageError(f"logo exceeds max size: {logo_size} > {DEFAULT_MAX_LOGO_BYTES}")
            logo_r2_key = build_r2_logo_key(owner, name, version, commit_sha, logo_path.suffix)
            logo_url = f"{public_base_url.rstrip('/')}/{logo_r2_key}"
            logo_asset = {
                "source_path": str(source_dir / logo_path.relative_to(clean_dir)),
                "r2_key": logo_r2_key,
                "url": logo_url,
                "sha256": sha256_file(logo_path),
                "size": logo_size,
                "content_type": LOGO_CONTENT_TYPES[logo_path.suffix.lower()],
            }

    size = zip_path.stat().st_size
    if size > max_bytes:
        raise PackageError(f"package exceeds max size: {size} > {max_bytes}")

    sha256 = sha256_file(zip_path)
    public_base = public_base_url.rstrip("/")
    download_url = f"{public_base}/{r2_key}"
    package = {
        "source": "r2",
        "url": download_url,
        "sha256": sha256,
        "size": size,
        "r2_key": r2_key,
    }
    result = {
        "name": name,
        "version": version,
        "commit_sha": commit_sha,
        "updated_at": updated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "zip_path": str(zip_path),
        "download_url": download_url,
        "sha256": sha256,
        "size": size,
        "package": package,
        "sec_scan": {"static": scan},
    }
    for field in ("display_name", "plugin_id", "description", "author"):
        if source_metadata.get(field):
            result[field] = source_metadata[field]
    if logo_asset:
        result["logo"] = logo_url
        result["logo_asset"] = logo_asset
    return result


def github_api_json(url: str, token: str | None = None) -> Any:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "shinsekai-plugin-registry-ci"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def github_api_json_or_none(url: str, token: str | None = None) -> Any | None:
    try:
        return github_api_json(url, token)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def ref_candidates(ref: str) -> list[str]:
    candidates = [ref]
    if ref.startswith("v") and len(ref) > 1:
        candidates.append(ref[1:])
    elif ref and ref[0].isdigit():
        candidates.append(f"v{ref}")
    return candidates


def resolve_commit_ref(owner: str, repo: str, refs: list[str], token: str | None = None) -> tuple[str, str]:
    for ref in refs:
        commit = github_api_json_or_none(f"https://api.github.com/repos/{owner}/{repo}/commits/{ref}", token)
        if commit is not None:
            return ref, commit["sha"]
    raise PackageError(f"could not resolve GitHub ref: {', '.join(refs)}")


def resolve_github_ref(owner: str, repo: str, configured_version: str | None, token: str | None = None) -> tuple[str, str, str]:
    if configured_version:
        ref, commit_sha = resolve_commit_ref(owner, repo, ref_candidates(configured_version), token)
        return configured_version, ref, commit_sha

    latest_release = github_api_json_or_none(f"https://api.github.com/repos/{owner}/{repo}/releases/latest", token)
    if isinstance(latest_release, dict) and latest_release.get("tag_name"):
        tag_name = str(latest_release["tag_name"])
        ref, commit_sha = resolve_commit_ref(owner, repo, ref_candidates(tag_name), token)
        return tag_name, ref, commit_sha

    tags = github_api_json(f"https://api.github.com/repos/{owner}/{repo}/tags?per_page=1", token)
    if isinstance(tags, list) and tags:
        tag = tags[0]
        tag_name = str(tag["name"])
        ref, commit_sha = resolve_commit_ref(owner, repo, ref_candidates(tag_name), token)
        return tag_name, ref, commit_sha

    repo_meta = github_api_json(f"https://api.github.com/repos/{owner}/{repo}", token)
    ref = repo_meta["default_branch"]
    commit = github_api_json(f"https://api.github.com/repos/{owner}/{repo}/commits/{ref}", token)
    return "v0.0.0", ref, commit["sha"]


def download_github_archive(
    owner: str,
    repo: str,
    ref: str,
    output: Path,
    token: str | None = None,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
) -> None:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "shinsekai-plugin-registry-ci"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com/repos/{owner}/{repo}/zipball/{ref}", headers=headers)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_archive_bytes:
                raise PackageError(f"archive exceeds max download size: {content_length} > {max_archive_bytes}")

            total = 0
            with output.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_archive_bytes:
                        raise PackageError(f"archive exceeds max download size: {total} > {max_archive_bytes}")
                    handle.write(chunk)
    except urllib.error.URLError as exc:
        raise PackageError(f"failed to download GitHub archive: {exc}") from exc
    except PackageError:
        output.unlink(missing_ok=True)
        raise


def extract_archive_to_source(
    archive_path: Path,
    dest_dir: Path,
    *,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_members: int = DEFAULT_MAX_ARCHIVE_MEMBERS,
    max_uncompressed_bytes: int = DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES,
) -> Path:
    if archive_path.stat().st_size > max_archive_bytes:
        raise PackageError(f"archive exceeds max download size: {archive_path.stat().st_size} > {max_archive_bytes}")

    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > max_members:
            raise PackageError(f"archive has too many files: {len(members)} > {max_members}")

        extracted_bytes = 0
        archive_root = archive_root_prefix(members)
        dest_dir.mkdir(parents=True, exist_ok=True)
        for member in members:
            if "\\" in member.filename:
                raise PackageError(f"unsafe archive path: {member.filename}")
            member_path = PurePosixPath(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise PackageError(f"unsafe archive path: {member.filename}")

            if member.is_dir() or should_exclude_archive_member(member_path, archive_root):
                continue

            extracted_bytes += member.file_size
            if extracted_bytes > max_uncompressed_bytes:
                raise PackageError(f"archive exceeds max uncompressed size: {extracted_bytes} > {max_uncompressed_bytes}")

            target = dest_dir.joinpath(*member_path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)

    roots = [path for path in dest_dir.iterdir() if path.is_dir()]
    if len(roots) == 1:
        return roots[0]
    return dest_dir


def load_plugins(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("plugins"), dict):
        return registry_object_values(data["plugins"])
    if isinstance(data, dict):
        return registry_object_values(data)
    raise PackageError("plugins.json must be an array or object.")


def registry_object_values(registry: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for name, value in registry.items():
        if not isinstance(value, dict):
            raise PackageError("each plugin entry must be an object.")
        entry = dict(value)
        # AstrBot-style generated registries often use the object key as the plugin name.
        entry.setdefault("name", name)
        entries.append(entry)
    return entries


def find_plugin(plugins: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for entry in plugins:
        if entry.get("name") == name:
            return entry
    raise PackageError(f"plugin not found: {name}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package one Shinsekai plugin into a clean zip.")
    parser.add_argument("--plugins-json", type=Path, default=Path("plugins.json"))
    parser.add_argument("--plugin-name", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--result-file", type=Path, required=True)
    parser.add_argument("--public-base-url", required=True)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--commit-sha")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        entry = find_plugin(load_plugins(args.plugins_json), args.plugin_name)
        owner, repo = normalize_repo_slug(str(entry.get("repo") or ""))
        configured_version = str(entry.get("version") or "").strip() or None
        fallback_version = configured_version
        if args.source_dir:
            source_dir = args.source_dir
            commit_sha = args.commit_sha or "local0000000"
            fallback_version = fallback_version or "v0.0.0"
        else:
            fallback_version, ref, commit_sha = resolve_github_ref(owner, repo, configured_version, args.github_token)
            archive_path = args.output_dir / f"{args.plugin_name}-source.zip"
            download_github_archive(owner, repo, ref, archive_path, args.github_token)
            extract_root = args.output_dir / f"{args.plugin_name}-source"
            if extract_root.exists():
                shutil.rmtree(extract_root)
            extract_root.mkdir(parents=True)
            source_dir = extract_archive_to_source(archive_path, extract_root)

        entry = dict(entry)
        entry.pop("version", None)
        result = package_local_plugin(
            source_dir=source_dir,
            entry=entry,
            output_dir=args.output_dir,
            commit_sha=commit_sha,
            public_base_url=args.public_base_url,
            max_bytes=args.max_bytes,
            fallback_version=fallback_version,
        )
        args.result_file.parent.mkdir(parents=True, exist_ok=True)
        args.result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (PackageError, urllib.error.URLError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
