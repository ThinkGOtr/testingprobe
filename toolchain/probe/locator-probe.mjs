#!/usr/bin/env node
// Locator yoklaması (TEKNIK-TASARIM §8.7, MIMARI-SOZLESME §2 `POST /locator-probe`).
//
//   node locator-probe.mjs '<json>'
//   json: {base_url, url_path, role, name, scope_test_id?, candidate_test_id?,
//          login?: {kullanici_adi, parola}, nav_timeout_ms, wait_ms}
//
// Demo uygulamasında `url_path`'i açar, getByRole(role, {name}) eşleşmelerini sayar (scope_test_id
// verilirse yalnızca o data-testid'li kapsayıcının içinde) ve tek eşleşmede data-testid'yi okur.
// Ek olarak:
// - `page_matches`: kapsam verildiyse aynı rol + adın sayfanın tamamındaki sayısı (kapsayıcı
//   yanlış mı, eleman mı yok ayrımı için),
// - `candidate`: `candidate_test_id` verilirse o testId'nin kapsamda kaç elemana çözüldüğü ve
//   bunlardan kaçının aynı rol + ada sahip olduğu (onarım adayının doğrulaması, §8.7),
// - `aria_snapshot`: kapsayıcının (yoksa sayfanın) aria snapshot'ı (rol + ad; ≤ 8000 karakter).
// Tarayıcı yalnızca base_url kaynağına istek atabilir (diğerleri iptal). Sayfa içeriği güvenilmeyen
// veridir; yalnızca sayılar ve öznitelik değerleri döner. Çıktı: tek satır JSON (stdout).
// Çıkış: 0 = yoklama yapıldı, 2 = hata ({"ok": false, "error": "..."}).
import { chromium } from "playwright";

const MAX_IDS = 20;
const MAX_ARIA = 8000;

function fail(message) {
  process.stdout.write(`${JSON.stringify({ ok: false, error: message })}\n`);
  process.exitCode = 2;
}

async function probe(input) {
  const origin = new URL(input.base_url).origin;
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      baseURL: input.base_url,
      locale: "tr-TR",
      timezoneId: "Europe/Istanbul",
      serviceWorkers: "block",
    });
    await context.route("**/*", (route) => {
      let reqOrigin = "";
      try {
        reqOrigin = new URL(route.request().url()).origin;
      } catch {
        reqOrigin = "";
      }
      return reqOrigin === origin ? route.continue() : route.abort("blockedbyclient");
    });
    let loggedIn = false;
    if (input.login) {
      const resp = await context.request.post("/api/auth/login", { data: input.login });
      if (!resp.ok()) throw new Error(`demo uygulamasına giriş başarısız: HTTP ${resp.status()}`);
      loggedIn = true;
    }
    try {
      const page = await context.newPage();
      page.setDefaultTimeout(input.wait_ms);
      const nav = await page.goto(input.url_path, { waitUntil: "load", timeout: input.nav_timeout_ms });
      const root = input.scope_test_id ? page.getByTestId(input.scope_test_id) : page;
      let scopeMatches = null;
      if (input.scope_test_id) {
        await root.first().waitFor({ state: "attached", timeout: input.wait_ms }).catch(() => undefined);
        scopeMatches = await root.count();
      }
      const matches = root.getByRole(input.role, { name: input.name });
      if (scopeMatches !== 0) {
        // Liste verisi istemcide yüklenir: ilk eşleşmeyi kısa süre bekle (yoksa 0 sayılır).
        await matches.first().waitFor({ state: "attached", timeout: input.wait_ms }).catch(() => undefined);
      }
      const count = scopeMatches === 0 ? 0 : await matches.count();
      const ids = count === 0 ? [] : await matches.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
      const pageMatches = input.scope_test_id ? await page.getByRole(input.role, { name: input.name }).count() : count;
      let candidate = null;
      if (input.candidate_test_id) {
        const cand = (scopeMatches === 0 ? page : root).getByTestId(input.candidate_test_id);
        const candCount = scopeMatches === 0 ? 0 : await cand.count();
        const withRole = candCount === 0 ? 0 : await cand.and(page.getByRole(input.role, { name: input.name })).count();
        candidate = { test_id: input.candidate_test_id, matches: candCount, role_name_matches: withRole };
      }
      let aria = null;
      try {
        const target = input.scope_test_id && scopeMatches === 1 ? root.first() : page.locator("body");
        aria = await target.ariaSnapshot({ timeout: input.wait_ms });
      } catch {
        aria = null;
      }
      return {
        ok: true,
        matches: count,
        test_id: count === 1 ? (ids[0] ?? null) : null,
        test_ids: ids.slice(0, MAX_IDS),
        scope_matches: scopeMatches,
        page_matches: pageMatches,
        candidate,
        aria_snapshot: typeof aria === "string" ? aria.slice(0, MAX_ARIA) : null,
        aria_snapshot_scope: aria === null ? null : input.scope_test_id && scopeMatches === 1 ? "scope" : "page",
        http_status: nav ? nav.status() : null,
        final_path: new URL(page.url()).pathname,
      };
    } finally {
      if (loggedIn) await context.request.post("/api/auth/logout").catch(() => undefined);
    }
  } finally {
    await browser.close();
  }
}

let input;
try {
  input = JSON.parse(process.argv[2] ?? "");
} catch {
  input = undefined;
}
if (!input || typeof input !== "object") {
  fail("girdi JSON'u okunamadı");
} else {
  try {
    const out = await probe(input);
    process.stdout.write(`${JSON.stringify(out)}\n`);
  } catch (err) {
    fail(err instanceof Error ? err.message : String(err));
  }
}
