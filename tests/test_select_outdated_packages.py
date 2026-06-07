from __future__ import annotations

import pytest

from scripts.registry import select_outdated_packages


def plugin(name: str, **overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "name": name,
        "repo": f"owner/{name}",
        "entry": f"{name}.plugin:Plugin",
    }
    entry.update(overrides)
    return entry


def generated(name: str, **overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "name": name,
        "commit_sha": "current",
        "download_url": f"https://cdn.example.com/{name}.zip",
        "package": {"url": f"https://cdn.example.com/{name}.zip"},
    }
    entry.update(overrides)
    return entry


def test_select_outdated_plugins_includes_missing_package_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        select_outdated_packages,
        "resolve_github_ref",
        lambda owner, repo, configured_version, github_token=None: calls.append(repo) or ("v1", "v1", "current"),
    )

    selected = select_outdated_packages.select_outdated_plugins(
        plugins=[plugin("demo")],
        generated_registry={"demo": {"name": "demo"}},
        github_token="token",
    )

    assert selected == ["demo"]
    assert calls == []


def test_select_outdated_plugins_detects_changed_remote_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        select_outdated_packages,
        "resolve_github_ref",
        lambda owner, repo, configured_version, github_token=None: ("v1", "v1", "newcommit"),
    )

    selected = select_outdated_packages.select_outdated_plugins(
        plugins=[plugin("demo")],
        generated_registry={"demo": generated("demo", commit_sha="oldcommit")},
        github_token="token",
    )

    assert selected == ["demo"]


def test_select_outdated_plugins_skips_current_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        select_outdated_packages,
        "resolve_github_ref",
        lambda owner, repo, configured_version, github_token=None: ("v1", "v1", "current"),
    )

    selected = select_outdated_packages.select_outdated_plugins(
        plugins=[plugin("demo")],
        generated_registry={"demo": generated("demo", commit_sha="current")},
        github_token="token",
    )

    assert selected == []
