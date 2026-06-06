from __future__ import annotations

import json
import urllib.error
import zipfile
from pathlib import Path

import pytest
import scripts.registry.package_plugin as package_plugin_module

from scripts.registry.package_plugin import (
    PackageError,
    build_r2_key,
    build_r2_logo_key,
    download_github_archive,
    extract_archive_to_source,
    load_plugins,
    package_local_plugin,
    resolve_github_ref,
    verify_entry_path,
)


class FakeResponse:
    def __init__(self, chunks: list[bytes], content_length: str | None = None) -> None:
        self.chunks = list(chunks)
        self.headers: dict[str, str] = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        return None

    def read(self, _size: int) -> bytes:
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


def make_plugin(root: Path) -> Path:
    plugin = root / "source"
    (plugin / "plugins" / "demo").mkdir(parents=True)
    (plugin / "plugins" / "demo" / "plugin.py").write_text("class DemoPlugin:\n    pass\n", encoding="utf-8")
    (plugin / "README.md").write_text("# Demo\n", encoding="utf-8")
    (plugin / ".env").write_text("SECRET=bad\n", encoding="utf-8")
    (plugin / ".env.production").write_text("SECRET=bad\n", encoding="utf-8")
    (plugin / "__pycache__").mkdir()
    (plugin / "__pycache__" / "plugin.pyc").write_bytes(b"cache")
    (plugin / ".github").mkdir()
    (plugin / ".github" / "workflow.yml").write_text("name: skip\n", encoding="utf-8")
    for dirname in (".cache", "cache", "caches", "log", "logs", "tmp", "temp", "node_modules", "build"):
        (plugin / dirname).mkdir()
        (plugin / dirname / "skip.txt").write_text("skip\n", encoding="utf-8")
    return plugin


def test_build_r2_key_uses_version_without_v_and_commit12() -> None:
    key = build_r2_key("owner", "demo_plugin", "v1.2.3", "abcdef1234567890")

    assert key == "plugins/owner/demo_plugin/1.2.3/demo_plugin-1.2.3-abcdef123456.zip"


def test_build_r2_logo_key_uses_assets_namespace_and_extension() -> None:
    key = build_r2_logo_key("owner", "demo_plugin", "v1.2.3", "abcdef1234567890", ".png")

    assert key == "assets/owner/demo_plugin/1.2.3/logo-abcdef123456.png"


def test_verify_entry_path_accepts_plugins_prefixed_module(tmp_path: Path) -> None:
    source = make_plugin(tmp_path)

    assert verify_entry_path(source, "plugins.demo.plugin:DemoPlugin") == Path("plugins/demo/plugin.py")


def test_verify_entry_path_accepts_without_plugins_prefix(tmp_path: Path) -> None:
    source = make_plugin(tmp_path)

    assert verify_entry_path(source, "demo.plugin:DemoPlugin") == Path("plugins/demo/plugin.py")


def test_verify_entry_path_accepts_flat_legacy_repo_with_plugin_name_prefix(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "plugin.py").write_text("class DemoPlugin:\n    pass\n", encoding="utf-8")

    assert verify_entry_path(source, "demo_plugin.plugin:DemoPlugin", "demo_plugin") == Path("plugin.py")
    assert verify_entry_path(source, "plugins.demo_plugin.plugin:DemoPlugin", "demo_plugin") == Path("plugin.py")


def test_verify_entry_path_rejects_missing_module(tmp_path: Path) -> None:
    source = make_plugin(tmp_path)

    with pytest.raises(PackageError, match="entry module"):
        verify_entry_path(source, "missing.plugin:Plugin")


def test_package_local_plugin_builds_clean_zip_and_metadata(tmp_path: Path) -> None:
    source = make_plugin(tmp_path)
    logo_bytes = b"\x89PNG\r\n\x1a\nlogo"
    (source / "logo.png").write_bytes(logo_bytes)
    output_dir = tmp_path / "out"
    entry = {
        "name": "demo_plugin",
        "repo": "owner/demo-plugin",
        "entry": "plugins.demo.plugin:DemoPlugin",
        "version": "v1.0.0",
    }

    result = package_local_plugin(
        source_dir=source,
        entry=entry,
        output_dir=output_dir,
        commit_sha="abcdef1234567890",
        public_base_url="https://cdn.example.com",
        max_bytes=16_777_216,
    )

    assert result["name"] == "demo_plugin"
    assert result["commit_sha"] == "abcdef1234567890"
    assert result["version"] == "v1.0.0"
    assert result["package"]["r2_key"] == "plugins/owner/demo_plugin/1.0.0/demo_plugin-1.0.0-abcdef123456.zip"
    assert result["download_url"] == "https://cdn.example.com/plugins/owner/demo_plugin/1.0.0/demo_plugin-1.0.0-abcdef123456.zip"
    assert result["logo"] == "https://cdn.example.com/assets/owner/demo_plugin/1.0.0/logo-abcdef123456.png"
    assert result["logo_asset"]["source_path"] == str(source / "logo.png")
    assert result["logo_asset"]["r2_key"] == "assets/owner/demo_plugin/1.0.0/logo-abcdef123456.png"
    assert result["logo_asset"]["content_type"] == "image/png"
    assert result["logo_asset"]["size"] == len(logo_bytes)
    assert len(result["logo_asset"]["sha256"]) == 64
    assert result["sec_scan"]["static"]["pass"] is True

    zip_path = Path(result["zip_path"])
    assert zip_path.exists()
    assert result["size"] == zip_path.stat().st_size
    assert len(result["sha256"]) == 64
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "plugins/demo/plugin.py" in names
    assert ".env" not in names
    assert ".env.production" not in names
    assert "__pycache__/plugin.pyc" not in names
    assert ".github/workflow.yml" not in names
    assert ".cache/skip.txt" not in names
    assert "cache/skip.txt" not in names
    assert "caches/skip.txt" not in names
    assert "log/skip.txt" not in names
    assert "logs/skip.txt" not in names
    assert "tmp/skip.txt" not in names
    assert "temp/skip.txt" not in names
    assert "node_modules/skip.txt" not in names
    assert "build/skip.txt" not in names


def test_package_local_plugin_rejects_static_scan_failure(tmp_path: Path) -> None:
    source = make_plugin(tmp_path)
    (source / "plugins" / "demo" / "plugin.py").write_text("eval(user_input)\n", encoding="utf-8")

    with pytest.raises(PackageError, match="static security scan failed"):
        package_local_plugin(
            source_dir=source,
            entry={
                "name": "demo_plugin",
                "repo": "owner/demo-plugin",
                "entry": "plugins.demo.plugin:DemoPlugin",
            },
            output_dir=tmp_path / "out",
            commit_sha="abcdef1234567890",
            public_base_url="https://cdn.example.com",
            max_bytes=16_777_216,
        )


def test_package_local_plugin_rejects_size_limit(tmp_path: Path) -> None:
    source = make_plugin(tmp_path)

    with pytest.raises(PackageError, match="exceeds max size"):
        package_local_plugin(
            source_dir=source,
            entry={
                "name": "demo_plugin",
                "repo": "owner/demo-plugin",
                "entry": "plugins.demo.plugin:DemoPlugin",
            },
            output_dir=tmp_path / "out",
            commit_sha="abcdef1234567890",
            public_base_url="https://cdn.example.com",
            max_bytes=10,
        )


def test_package_result_is_json_serializable(tmp_path: Path) -> None:
    source = make_plugin(tmp_path)
    result = package_local_plugin(
        source_dir=source,
        entry={
            "name": "demo_plugin",
            "repo": "owner/demo-plugin",
            "entry": "plugins.demo.plugin:DemoPlugin",
        },
        output_dir=tmp_path / "out",
        commit_sha="abcdef1234567890",
        public_base_url="https://cdn.example.com",
        max_bytes=16_777_216,
    )

    json.dumps(result)


def test_extract_archive_to_source_rejects_zip_slip(tmp_path: Path) -> None:
    archive_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../evil.py", "pass\n")

    with pytest.raises(PackageError, match="unsafe archive path"):
        extract_archive_to_source(archive_path, tmp_path / "out")


def test_extract_archive_to_source_rejects_absolute_path(tmp_path: Path) -> None:
    archive_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("/evil.py", "pass\n")

    with pytest.raises(PackageError, match="unsafe archive path"):
        extract_archive_to_source(archive_path, tmp_path / "out")


def test_extract_archive_to_source_rejects_backslash_path(tmp_path: Path) -> None:
    archive_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("root\\..\\evil.py", "pass\n")

    with pytest.raises(PackageError, match="unsafe archive path"):
        extract_archive_to_source(archive_path, tmp_path / "out")


def test_extract_archive_to_source_enforces_member_and_size_limits(tmp_path: Path) -> None:
    archive_path = tmp_path / "large.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("root/plugin.py", "x" * 20)

    with pytest.raises(PackageError, match="max download size"):
        extract_archive_to_source(archive_path, tmp_path / "out1", max_archive_bytes=1)

    with pytest.raises(PackageError, match="too many files"):
        extract_archive_to_source(archive_path, tmp_path / "out2", max_members=0)

    with pytest.raises(PackageError, match="max uncompressed size"):
        extract_archive_to_source(archive_path, tmp_path / "out3", max_uncompressed_bytes=1)


def test_extract_archive_to_source_skips_excluded_members(tmp_path: Path) -> None:
    archive_path = tmp_path / "source.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("root/plugins/demo/plugin.py", "pass\n")
        archive.writestr("root/node_modules/skip.js", "skip\n")
        archive.writestr("root/.env.production", "SECRET=bad\n")

    source = extract_archive_to_source(archive_path, tmp_path / "out")

    assert (source / "plugins" / "demo" / "plugin.py").exists()
    assert not (source / "node_modules" / "skip.js").exists()
    assert not (source / ".env.production").exists()


def test_download_github_archive_rejects_large_content_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_urlopen(_request: object, timeout: int = 60) -> FakeResponse:
        return FakeResponse([b"ignored"], content_length="10")

    output = tmp_path / "archive.zip"
    monkeypatch.setattr(package_plugin_module.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(PackageError, match="max download size"):
        download_github_archive("owner", "repo", "ref", output, max_archive_bytes=5)

    assert not output.exists()


def test_download_github_archive_rejects_large_stream_without_content_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_urlopen(_request: object, timeout: int = 60) -> FakeResponse:
        return FakeResponse([b"abcd", b"efg"])

    output = tmp_path / "archive.zip"
    monkeypatch.setattr(package_plugin_module.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(PackageError, match="max download size"):
        download_github_archive("owner", "repo", "ref", output, max_archive_bytes=5)

    assert not output.exists()


def test_load_plugins_uses_object_key_as_name(tmp_path: Path) -> None:
    registry = tmp_path / "plugins.json"
    registry.write_text(
        json.dumps(
            {
                "demo_plugin": {
                    "repo": "owner/demo-plugin",
                    "entry": "plugins.demo.plugin:DemoPlugin",
                }
            }
        ),
        encoding="utf-8",
    )

    plugins = load_plugins(registry)

    assert plugins[0]["name"] == "demo_plugin"


def test_resolve_github_ref_prefers_latest_release(monkeypatch: pytest.MonkeyPatch) -> None:
    commit_sha = "a" * 40

    def fake_github_api_json(url: str, token: str | None = None) -> object:
        if url.endswith("/releases/latest"):
            return {"tag_name": "v2.0.0"}
        if url.endswith("/commits/v2.0.0"):
            return {"sha": commit_sha}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(package_plugin_module, "github_api_json", fake_github_api_json)

    assert resolve_github_ref("owner", "repo", None, "token") == ("v2.0.0", "v2.0.0", commit_sha)


def test_resolve_github_ref_falls_back_to_latest_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    commit_sha = "c" * 40

    def fake_github_api_json(url: str, token: str | None = None) -> object:
        if url.endswith("/releases/latest"):
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        if url.endswith("/tags?per_page=1"):
            return [{"name": "v1.5.0", "commit": {"sha": "tag-object-sha"}}]
        if url.endswith("/commits/v1.5.0"):
            return {"sha": commit_sha}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(package_plugin_module, "github_api_json", fake_github_api_json)

    assert resolve_github_ref("owner", "repo", None, "token") == ("v1.5.0", "v1.5.0", commit_sha)


def test_resolve_github_ref_falls_back_from_plain_version_to_v_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    commit_sha = "b" * 40

    def fake_github_api_json(url: str, token: str | None = None) -> object:
        if url.endswith("/commits/1.0.0"):
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        if url.endswith("/commits/v1.0.0"):
            return {"sha": commit_sha}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(package_plugin_module, "github_api_json", fake_github_api_json)

    assert resolve_github_ref("owner", "repo", "1.0.0", "token") == ("1.0.0", "v1.0.0", commit_sha)


def test_resolve_github_ref_propagates_non_404_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_github_api_json(url: str, token: str | None = None) -> object:
        raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)

    monkeypatch.setattr(package_plugin_module, "github_api_json", fake_github_api_json)

    with pytest.raises(urllib.error.HTTPError):
        resolve_github_ref("owner", "repo", "1.0.0", "token")
