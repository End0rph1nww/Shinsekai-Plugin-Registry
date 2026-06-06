# Plugin Trust Levels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a conservative trust model where new plugins publish as Community by default, Verified is granted only through a separate maintainer review path, and users see install-time risk warnings for unverified plugins.

**Architecture:** The Registry remains the source of truth for trust fields. The generated registry carries trust metadata to the plugin market and Shinsekai client. Verification requests create GitHub Issues, and maintainer verification creates a Registry PR instead of directly mutating R2 or a database.

**Tech Stack:** Python registry scripts/tests, GitHub Actions issue templates/workflows, Vue plugin market, React/Tauri Shinsekai client.

---

### Task 1: Registry Trust Fields

**Files:**
- Modify: `scripts/registry/parse_issue_submission.py`
- Modify: `scripts/registry/validate_plugins.py`
- Modify: `scripts/registry/update_generated_registry.py`
- Modify: `tests/test_parse_issue_submission.py`
- Modify: `tests/test_validate_plugins.py`
- Modify: `tests/test_update_generated_registry.py`
- Modify: `README.md`

- [x] Add defaults for issue-created plugins:
  - `trust_level: "community"`
  - `verified: false`
  - `review.status: "ci_passed"`
- [x] Validate `trust_level` as one of `community`, `verified`, `verified_update_pending`, `blocked`.
- [x] Validate `verified` is boolean when present.
- [x] Validate `review` is an object when present.
- [x] Keep trust fields in generated `plugin_cache_original.json`.
- [x] Add tests for default Community status and valid Verified entries.

### Task 2: Verification Request Entry

**Files:**
- Create: `.github/ISSUE_TEMPLATE/VERIFICATION_REQUEST.yml`
- Create: `.github/workflows/verification-request-to-pr.yml`
- Create: `scripts/registry/mark_plugin_verified.py`
- Create: `tests/test_mark_plugin_verified.py`
- Modify: `README.md`

- [x] Add an Issue template for maintainers/users to request review of an existing plugin.
- [x] Add a script that marks one plugin as Verified for a reviewed commit/version.
- [x] Add a label-triggered parser so maintainers can approve by adding `verification-approved`.
- [x] The script must update `plugins.json`, not generated files.
- [x] The workflow must create or update `verification/{plugin-name}` branch and PR.
- [x] The workflow must support manual dispatch as a fallback and `plugin-verification` + `verification-approved` labeled Issues as the main approval path.

### Task 3: Plugin Market Trust UI

**Files:**
- Modify: `src/utils/pluginNormalizer.js`
- Modify: `src/components/PluginCard.vue`
- Modify: `src/components/PluginDetails.vue`
- Modify: `src/assets/theme.css`

- [x] Normalize `trust_level`, `verified`, and `review`.
- [x] Show a green `Verified` badge only for `verified=true` and `trust_level=verified`.
- [x] Show `Community` for unverified plugins.
- [x] Show `Previously verified / pending review` for `verified_update_pending`.
- [x] Add an `Apply for verification` link that opens a GitHub Verification Request issue with plugin metadata.

### Task 4: Shinsekai Client Trust UI

**Files:**
- Modify: `core/plugins/registry_catalog.py`
- Modify: `frontend_bridge_core/plugin_catalog.py`
- Modify: `frontend/src/shared/platform/types.ts`
- Modify: `frontend/src/features/plugin-manager/PluginCatalogPanel.tsx`
- Modify: `frontend/src/features/plugin-manager/PluginManagerPage.css`

- [x] Parse and bridge trust metadata.
- [x] Show trust badges in catalog cards.
- [x] Show risk warning in install dialog for Community plugins.
- [x] Show softer warning for `verified_update_pending`.
- [x] Keep Verified install dialog concise while still showing package SHA/source.

### Task 5: Verification

**Commands:**
- Registry:
  - `python -m pytest tests -q`
  - `python scripts\registry\validate_plugins.py plugins.json`
  - `python -c "import yaml; yaml.safe_load(open('.github/workflows/verification-request-to-pr.yml', encoding='utf-8')); print('workflow yaml ok')"`
- Market:
  - `npm run build`
- Shinsekai client:
  - `pnpm --dir frontend format:check`
  - `pnpm --dir frontend test -- --run`

- [x] Run focused tests first.
- [x] Run full available checks before pushing.
- [x] Push Registry, Market, and Shinsekai main fork branches only after checks pass.
