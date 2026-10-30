# toolchain

Single image (`testingprobe-toolchain:local`) shared by `toolchain-worker` (:8100), `test-runner`
(:8200) and `playwright-mcp` (:8931). Base: `mcr.microsoft.com/playwright:v<.playwright-version>-noble`
(digest-pinned), so browsers come from the image (`/ms-playwright`) and exist only once.

## Playwright version unity (FR-012)

`@playwright/mcp@0.0.83` depends on `playwright@1.64.0-alpha-1790635538000`, whose browsers are
Chromium revision **1247**; the 1.64.1 base image ships revision **1248**, so the MCP could not
launch a browser out of the box. Choice: `package.json` `overrides` force `playwright` and
`playwright-core` to **1.64.1** for the whole tree. Result: one `playwright-core` in the image, the
MCP reports server version `1.64.1` and uses `/ms-playwright/chromium-1248`; no extra browser
download (~+300 MB avoided). The build fails if the installed `playwright-core` differs from the
`PLAYWRIGHT_VERSION` build arg. When bumping `.playwright-version`, update `@playwright/test` and
the overrides in `package.json`, run `npm install --package-lock-only`, and re-check the MCP with an
`initialize` + `browser_navigate` call.

Alternatives not taken: installing Chromium 1247 next to 1248 (disk, two browser versions);
`--executable-path` to the 1248 binary while keeping the alpha core (untested protocol pairing).

## playwright-mcp flags

`bin/playwright-mcp`: `--headless --browser chromium --host 0.0.0.0 --port 8931 --allowed-hosts '*'
--isolated --caps=testing --allowed-origins "$MCP_ALLOWED_ORIGINS" --output-dir /tmp/playwright-mcp`.

- `--browser chromium` is required: the default is the `chrome` channel (`/opt/google/chrome`), absent here.
- `testing` is not listed under `--caps` in `--help` (only vision, pdf, devtools) but is accepted
  and enables `browser_generate_locator` and `browser_verify_*`. No `vision`.
- `MCP_ALLOWED_ORIGINS` is mandatory (an empty value would mean "allow all"). Origins outside it
  fail with `net::ERR_BLOCKED_BY_CLIENT`; per upstream this is not a security boundary — network
  isolation (research R5) is.
- Endpoint: Streamable HTTP at `/mcp` (legacy SSE at `/sse`).

## Python

`pyproject.toml` + `uv.lock` (Python 3.12 from the base image, `uv sync --frozen`); `uv` is only
mounted at build time. No model SDKs (constitution II). `/health` per
`specs/001-dev-foundation/contracts/health.md`: `playwright` compares the installed
`playwright-core` with env `PLAYWRIGHT_VERSION` (503 on mismatch or if unset).
