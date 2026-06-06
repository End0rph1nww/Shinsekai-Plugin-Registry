from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.registry.update_generated_registry import (
    detect_changed_plugin_names,
    merge_package_results,
    merge_repo_metadata,
    update_generated_registry,
)


def plugin(name: str, **overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "name": name,
        "author": "End0rph1n",
        "repo": f"owner/{name}",
        "description": "Description",
        "entry": f"plugins.{name}.plugin:Plugin",
    }
    entry.update(overrides)
    return entry


def test_detect_changed_plugin_names_for_added_and_modified_entries() -> None:
    old = [plugin("a"), plugin("b", description="old")]
    new = [plugin("a"), plugin("b", description="new"), plugin("c")]

    assert detect_changed_plugin_names(old, new) == ["b", "c"]


def test_detect_changed_plugin_names_accepts_object_key_names() -> None:
    old_entry = plugin("demo_plugin")
    old_entry.pop("name")
    new_entry = plugin("demo_plugin", description="New")
    new_entry.pop("name")

    assert detect_changed_plugin_names({"demo_plugin": old_entry}, {"demo_plugin": new_entry}) == ["demo_plugin"]


def test_merge_package_results_writes_object_cache() -> None:
    registry = [plugin("demo_plugin", description="Demo")]
    package = {
        "name": "demo_plugin",
        "version": "v1.0.0",
        "commit_sha": "abcdef1234567890",
        "updated_at": "2026-06-06T00:00:00Z",
        "download_url": "https://cdn.example.com/plugins/demo.zip",
        "sha256": "a" * 64,
        "size": 123,
        "package": {
            "source": "r2",
            "url": "https://cdn.example.com/plugins/demo.zip",
            "sha256": "a" * 64,
            "size": 123,
            "r2_key": "plugins/owner/demo/1.0.0/demo.zip",
        },
        "logo": "https://cdn.example.com/assets/owner/demo/1.0.0/logo-abcdef123456.png",
        "logo_asset": {
            "source_path": "source/logo.png",
            "r2_key": "assets/owner/demo/1.0.0/logo-abcdef123456.png",
        },
        "sec_scan": {"static": {"pass": True, "msg": "No blocked patterns found.", "findings": []}},
    }

    generated = merge_package_results(registry, [package])

    assert isinstance(generated, dict)
    assert generated["demo_plugin"]["name"] == "demo_plugin"
    assert generated["demo_plugin"]["description"] == "Demo"
    assert generated["demo_plugin"]["download_url"] == "https://cdn.example.com/plugins/demo.zip"
    assert generated["demo_plugin"]["package"]["source"] == "r2"
    assert generated["demo_plugin"]["logo"] == "https://cdn.example.com/assets/owner/demo/1.0.0/logo-abcdef123456.png"
    assert "logo_asset" not in generated["demo_plugin"]


def test_merge_package_results_accepts_object_key_names() -> None:
    entry = plugin("demo_plugin")
    entry.pop("name")
    package = {
        "name": "demo_plugin",
        "download_url": "https://cdn.example.com/plugins/demo.zip",
        "package": {"source": "r2"},
    }

    generated = merge_package_results({"demo_plugin": entry}, [package])

    assert generated["demo_plugin"]["name"] == "demo_plugin"
    assert generated["demo_plugin"]["download_url"] == "https://cdn.example.com/plugins/demo.zip"


def test_merge_repo_metadata_adds_github_counts_without_overwriting_package_timestamp() -> None:
    registry = {
        "demo_plugin": {
            **plugin("demo_plugin", updated_at="2026-06-06T00:00:00Z"),
            "package": {"url": "https://cdn.example.com/plugins/demo.zip"},
        }
    }

    generated = merge_repo_metadata(
        registry,
        {
            "demo_plugin": {
                "stars": 42,
                "forks": 7,
                "repo_updated_at": "2026-06-05T00:00:00Z",
            }
        },
    )

    assert generated["demo_plugin"]["stars"] == 42
    assert generated["demo_plugin"]["stargazers_count"] == 42
    assert generated["demo_plugin"]["forks"] == 7
    assert generated["demo_plugin"]["forks_count"] == 7
    assert generated["demo_plugin"]["repo_updated_at"] == "2026-06-05T00:00:00Z"
    assert generated["demo_plugin"]["updated_at"] == "2026-06-06T00:00:00Z"
    assert generated["demo_plugin"]["package"]["url"] == "https://cdn.example.com/plugins/demo.zip"


def test_merge_package_results_preserves_existing_package_metadata() -> None:
    registry = [plugin("old_plugin", description="Fresh source"), plugin("new_plugin")]
    base = {
        "old_plugin": {
            **plugin("old_plugin", description="Old generated source"),
            "download_url": "https://cdn.example.com/plugins/old.zip",
            "sha256": "b" * 64,
            "size": 456,
            "package": {
                "source": "r2",
                "url": "https://cdn.example.com/plugins/old.zip",
                "sha256": "b" * 64,
                "size": 456,
                "r2_key": "plugins/owner/old/1.0.0/old.zip",
            },
            "sec_scan": {"static": {"pass": True}},
        }
    }
    package = {
        "name": "new_plugin",
        "download_url": "https://cdn.example.com/plugins/new.zip",
        "sha256": "a" * 64,
        "size": 123,
        "package": {"source": "r2", "url": "https://cdn.example.com/plugins/new.zip"},
    }

    generated = merge_package_results(registry, [package], base)

    assert generated["old_plugin"]["description"] == "Fresh source"
    assert generated["old_plugin"]["download_url"] == "https://cdn.example.com/plugins/old.zip"
    assert generated["old_plugin"]["package"]["r2_key"] == "plugins/owner/old/1.0.0/old.zip"
    assert generated["new_plugin"]["download_url"] == "https://cdn.example.com/plugins/new.zip"


def test_update_generated_registry_writes_cache_and_md5(tmp_path: Path) -> None:
    plugins_json = tmp_path / "plugins.json"
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    output = tmp_path / "plugin_cache_original.json"
    md5_output = tmp_path / "plugins-md5.json"
    plugins_json.write_text(json.dumps([plugin("demo_plugin")]), encoding="utf-8")
    (result_dir / "demo_plugin.json").write_text(
        json.dumps(
            {
                "name": "demo_plugin",
                "version": "v1.0.0",
                "commit_sha": "abcdef1234567890",
                "updated_at": "2026-06-06T00:00:00Z",
                "download_url": "https://cdn.example.com/plugins/demo.zip",
                "sha256": "a" * 64,
                "size": 123,
                "package": {
                    "source": "r2",
                    "url": "https://cdn.example.com/plugins/demo.zip",
                    "sha256": "a" * 64,
                    "size": 123,
                    "r2_key": "plugins/owner/demo/1.0.0/demo.zip",
                },
                "sec_scan": {"static": {"pass": True, "msg": "No blocked patterns found.", "findings": []}},
            }
        ),
        encoding="utf-8",
    )

    update_generated_registry(
        plugins_json=plugins_json,
        package_results_dir=result_dir,
        output=output,
        md5_output=md5_output,
        dry_run=False,
    )

    generated_bytes = output.read_bytes()
    generated_text = generated_bytes.decode("utf-8")
    assert json.loads(generated_text)["demo_plugin"]["download_url"] == "https://cdn.example.com/plugins/demo.zip"
    assert json.loads(md5_output.read_text(encoding="utf-8")) == {
        "md5": hashlib.md5(generated_bytes).hexdigest()
    }


def test_update_generated_registry_uses_existing_cache_as_base(tmp_path: Path) -> None:
    plugins_json = tmp_path / "plugins.json"
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    output = tmp_path / "plugin_cache_original.json"
    md5_output = tmp_path / "plugins-md5.json"
    plugins_json.write_text(json.dumps([plugin("old_plugin"), plugin("new_plugin")]), encoding="utf-8")
    output.write_text(
        json.dumps(
            {
                "old_plugin": {
                    **plugin("old_plugin"),
                    "download_url": "https://cdn.example.com/plugins/old.zip",
                    "package": {"source": "r2", "url": "https://cdn.example.com/plugins/old.zip"},
                }
            }
        ),
        encoding="utf-8",
    )
    (result_dir / "new_plugin.json").write_text(
        json.dumps(
            {
                "name": "new_plugin",
                "download_url": "https://cdn.example.com/plugins/new.zip",
                "package": {"source": "r2", "url": "https://cdn.example.com/plugins/new.zip"},
            }
        ),
        encoding="utf-8",
    )

    update_generated_registry(
        plugins_json=plugins_json,
        package_results_dir=result_dir,
        output=output,
        md5_output=md5_output,
        dry_run=False,
    )

    generated = json.loads(output.read_text(encoding="utf-8"))
    assert generated["old_plugin"]["download_url"] == "https://cdn.example.com/plugins/old.zip"
    assert generated["new_plugin"]["download_url"] == "https://cdn.example.com/plugins/new.zip"


def test_update_generated_registry_dry_run_does_not_write(tmp_path: Path) -> None:
    plugins_json = tmp_path / "plugins.json"
    plugins_json.write_text(json.dumps([plugin("demo_plugin")]), encoding="utf-8")
    output = tmp_path / "plugin_cache_original.json"
    md5_output = tmp_path / "plugins-md5.json"

    update_generated_registry(
        plugins_json=plugins_json,
        package_results_dir=tmp_path / "missing",
        output=output,
        md5_output=md5_output,
        dry_run=True,
        plugin_names=["demo_plugin"],
    )

    assert not output.exists()
    assert not md5_output.exists()
