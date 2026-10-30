# Contract: /health

HTTP servislerin tümü (`core-api`, `review-portal`, `demo-app-api`, `demo-app-web`, `toolchain-worker`, `test-runner`) `GET /health` sunar.

**200 OK**
```json
{ "service": "core-api", "status": "ok", "version": "0.1.0", "checks": { "db": "ok" } }
```
**503 Service Unavailable** — herhangi bir bağımlılık kontrolü başarısız:
```json
{ "service": "core-api", "status": "degraded", "version": "0.1.0", "checks": { "db": "error: connection refused" } }
```

| Servis | `checks` |
|---|---|
| core-api | `db` (`tp`) |
| core-worker | (HTTP yok) sağlık: Postgres'e bağlanıp `job` tablosunu okuyabiliyor mu — compose healthcheck komutu |
| demo-app-api | `db` (`demoapp`) |
| toolchain-worker | `node`, `playwright` (sürüm `.playwright-version` ile eşleşiyor mu) |
| test-runner | `playwright` |
| playwright-mcp | (HTTP MCP) compose healthcheck: TCP 8931 |
| review-portal, demo-app-web | yok (statik; nginx 200) |
| postgres | compose healthcheck: `pg_isready` |
