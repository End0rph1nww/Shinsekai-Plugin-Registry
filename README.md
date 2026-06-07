# Shinsekai Plugin Registry

This repository is the reviewed source of truth for Shinsekai community plugins.

## Submit a Plugin

Authors should submit plugin metadata through the Shinsekai plugin market or the local submit helper in the Shinsekai client. Both routes generate the same JSON contract and open the `Publish Plugin` GitHub Issue template.

```json
{
  "display_name": "Human-readable plugin name",
  "desc": "Short description",
  "author": "author",
  "repo": "https://github.com/owner/repo",
  "lowest_shinsekai_version": ">=0.2.0",
  "tags": [],
  "social_link": ""
}
```

The issue workflow parses the fenced JSON block, validates it, updates `plugins.json` on a `submission/issue-{number}` branch, and opens a maintainer-review PR.

If branch pushes from the default `GITHUB_TOKEN` should trigger downstream PR validation, configure a `REGISTRY_BOT_TOKEN` secret with the minimum repository permissions needed for contents, pull requests, and issues. Without that bot token, GitHub may suppress workflows triggered by bot-created pushes.

## Registry Rules

- `display_name`, `desc`, `author`, and `repo` are required for new issue submissions.
- `repo` in a submission must be `https://github.com/{owner}/{repo}` and must not end with `.git`.
- `desc` must be 200 characters or fewer.
- `tags` must contain at most 5 non-empty strings.
- The generated PR keeps `plugins.json` compatible with the current registry shape.

## Validate Locally

```powershell
python -m pytest tests -q
python scripts\registry\validate_plugins.py plugins.json
```

This PR stage only implements submission validation and maintainer-review PR creation. Packaging approved plugins to R2 belongs to the follow-up Registry package CI stage.
