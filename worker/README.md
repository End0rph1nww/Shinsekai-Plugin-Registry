# Plugin download gateway

This Worker keeps package objects and the generated registry in the existing
`shinsekai-plugin-registry-prod` R2 bucket while adding exact, queryable download
counts in D1.

## Counting model

- Only a successful package `GET` carrying a valid UUIDv4
  `X-Shinsekai-Download-Id` creates a download event.
- Shinsekai creates that ID once per install attempt. Client retries and any
  Cloudflare edge re-fetches reuse the ID, and D1's primary key makes the
  increment idempotent.
- Direct or anonymous package requests, `HEAD`, missing objects, and registry
  requests are not counted. The metric therefore represents installs initiated
  by compatible Shinsekai clients rather than raw HTTP traffic.
- Raw event IDs are retained for 30 days to cover delayed retries. The scheduled
  cleanup removes only those IDs; `plugin_download_stats` keeps lifetime totals.
- The registry endpoint overlays each total as `download_count` and rewrites
  package URLs through the gateway.

D1 is used instead of KV because the insert plus trigger increment is atomic and
can enforce retry deduplication. Analytics Engine remains suitable for traffic
analysis, but it is not the source of truth for a precise marketplace ranking.

## Endpoints

- `GET /health`
- `GET /registry/plugin_cache_original.json`
- `GET /plugins/:owner/:plugin/:version/:file.zip`

Production uses `https://downloads.shinsekai.studio`. The old R2 domains remain in
place as origins and rollback paths.

## Development and deployment

```powershell
npm install
npm run types
npm test
npm run check
npx wrangler d1 migrations apply shinsekai-plugin-downloads --remote
npm run deploy
```

After changing `wrangler.jsonc`, regenerate and commit
`worker-configuration.d.ts`.
