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
  "shinsekai_version": ">=0.2.0",
  "tags": [],
  "social_link": ""
}
```

The issue workflow parses the fenced JSON block, validates it, reads the submitted GitHub repository to infer the plugin `name` and `entry`, updates `plugins.json` on a `submission/issue-{number}` branch, and opens a maintainer-review PR. Plugin package version and logo assets are handled by the package CI after the registry PR is merged.

New plugin submissions are listed as Community plugins by default:

```json
{
  "trust_level": "community",
  "verified": false,
  "review": {
    "status": "ci_passed"
  }
}
```

This first review is an inclusion check, not a full security audit. Maintainer verification is a separate follow-up path through the `Verification Request` issue template and `Create Plugin Verification PR` workflow. Verified status is bound to the reviewed package commit and version; if a verified plugin publishes a different commit or version, generated registry output is downgraded to `verified_update_pending` until maintainers review it again.

## Verify a Plugin

After a plugin is already listed as Community, authors can open a `Verification Request` issue from the plugin market. The issue contains the reviewed plugin name, version, commit, package hash, and package URL.

Maintainers approve a verification request by adding the `verification-approved` label. The `plugin-verification` label is useful for filtering verification requests, but the approval workflow only requires `verification-approved` and a valid verification JSON payload. The label-triggered workflow parses the issue JSON, records the labeling maintainer as `reviewed_by`, updates `plugins.json` on a `verification/{plugin-name}` branch, opens a PR, comments the PR URL back to the issue, and closes the issue as completed. Maintainers still merge that PR manually after reviewing the diff.

Maintainers reject a verification request by adding the `verification-rejected` label. The rejection workflow comments on the issue and closes it as not planned without changing `plugins.json`.

The `Create Plugin Verification PR` workflow also keeps a manual `workflow_dispatch` entry as a fallback for cases where an issue payload needs correction.

If branch pushes from the default `GITHUB_TOKEN` should trigger downstream PR validation, configure a `REGISTRY_BOT_TOKEN` secret with the minimum repository permissions needed for contents, pull requests, and issues. Without that bot token, GitHub may suppress workflows triggered by bot-created pushes.

## Registry Rules

- `display_name`, `desc`, `author`, and `repo` are required for new issue submissions.
- `repo` in a submission must be `https://github.com/{owner}/{repo}` and must not end with `.git`.
- `desc` must be 200 characters or fewer.
- `shinsekai_version` is optional compatibility guidance for users and must be a non-empty string when provided.
- `tags` must contain at most 5 non-empty strings.
- `trust_level` must be `community`, `verified`, `verified_update_pending`, or `blocked`.
- `verified=true` is only valid with `trust_level=verified` and a complete maintainer `review` object.
- The generated PR keeps `plugins.json` compatible with the current registry shape.

## Validate Locally

```powershell
python -m pytest tests -q
python scripts\registry\validate_plugins.py plugins.json
```

## Generated Registry and R2 Distribution

Maintainers approve submissions by merging the generated registry PR. The package workflow then builds clean plugin zips, uploads them to R2, updates `plugin_cache_original.json` and `plugins-md5.json`, and mirrors those generated JSON files to R2:

```text
registry/plugin_cache_original.json
registry/plugins-md5.json
plugins/<owner>/<plugin>/<version>/<zip>
assets/<owner>/<plugin>/<version>/logo-<commit>.png
```

Clients and the plugin market should prefer the R2 `registry/plugin_cache_original.json` URL for fresh reads. The GitHub Raw copy remains useful as a fallback and review artifact, but it can lag behind `main` because of Raw CDN caching.

The workflow also refreshes GitHub repository metadata on a schedule. Scheduled runs update `stars`, `forks`, and `repo_updated_at` in the generated registry without rebuilding every plugin package. To force this manually, run `Publish Plugin Packages` with `metadata_only=true` and `dry_run=false`.

Plugin logos can be committed directly in a plugin repository. During packaging, the workflow looks for `logo.png`, `logo.jpg`, `logo.jpeg`, or `logo.webp` in the repository root or common asset folders such as `assets/`, `static/`, `public/`, `resources/`, `images/`, and `img/`. Valid logos are uploaded to R2 under `assets/` and the generated registry receives the public `logo` URL.
