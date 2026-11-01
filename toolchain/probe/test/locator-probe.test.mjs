// locator-probe.mjs gerçek Chromium ile (Playwright 1.64.1): `make break` sonrası katalog sayfasının
// yerel bir kopyasında kapsamlı yoklama, onarım adayı, aria snapshot. Çalıştırma:
//   cd toolchain && npm ci --ignore-scripts && node --test probe/test/
// (tarayıcılar: imajda /ms-playwright; yerelde `npx playwright install chromium`).
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";

const PROBE = fileURLToPath(new URL("../locator-probe.mjs", import.meta.url));

// demo-app/web CatalogPage.tsx ile aynı yapı; demo/break-locator dalındaki gibi testId "cart-add".
const card = (kod, ad, testId) => `
  <article class="product-card" data-testid="product-card-${kod}" aria-labelledby="product-title-${kod}">
    <div class="product-visual" aria-hidden="true"><span>${ad[0]}</span></div>
    <div class="product-body">
      <p class="product-code">${kod}</p>
      <h2 id="product-title-${kod}">${ad}</h2>
      <p class="product-price" data-testid="product-price-${kod}">25,00 TL</p>
      <label for="qty-${kod}">Adet</label>
      <input id="qty-${kod}" data-testid="qty-input-${kod}" type="number" value="1">
      <button type="button" data-testid="${testId}">Sepete ekle</button>
      <p role="status" data-testid="product-status-${kod}"></p>
    </div>
  </article>`;

const CATALOG = `<!doctype html><html lang="tr"><head><title>Katalog</title></head><body>
  <main><h1>Ürün kataloğu</h1>
  <img src="http://example.invalid/dis-kaynak.png" alt="">
  <div data-testid="product-list">
    ${card("P-001", "Portakal Gazozu", "cart-add")}
    ${card("P-002", "Maden Suyu", "cart-add")}
  </div></main></body></html>`;

let server;
let baseUrl;
const logins = [];

before(async () => {
  server = createServer((req, res) => {
    if (req.method === "POST" && req.url === "/api/auth/login") {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        const data = JSON.parse(body || "{}");
        logins.push(data.kullanici_adi);
        res.writeHead(data.parola === "Demo123!" ? 200 : 401, { "content-type": "application/json" });
        res.end("{}");
      });
      return;
    }
    if (req.method === "POST" && req.url === "/api/auth/logout") {
      res.writeHead(204).end();
      return;
    }
    if (req.url === "/katalog") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" }).end(CATALOG);
      return;
    }
    res.writeHead(404).end();
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  baseUrl = `http://127.0.0.1:${server.address().port}`;
});

after(() => server.close());

function probe(extra) {
  const input = {
    base_url: baseUrl,
    url_path: "/katalog",
    role: "button",
    name: "Sepete ekle",
    login: { kullanici_adi: "bayi1", parola: "Demo123!" },
    nav_timeout_ms: 10_000,
    wait_ms: 1_000,
    ...extra,
  };
  return new Promise((resolve) => {
    execFile(process.execPath, [PROBE, JSON.stringify(input)], { timeout: 60_000 }, (err, stdout) => {
      const lines = stdout.trim().split("\n");
      resolve({ code: err ? err.code : 0, out: JSON.parse(lines[lines.length - 1]) });
    });
  });
}

test("kapsamlı yoklama: product-card-P-001 içinde tek 'Sepete ekle' → cart-add", async () => {
  const { code, out } = await probe({ scope_test_id: "product-card-P-001", candidate_test_id: "cart-add" });
  assert.equal(code, 0);
  assert.equal(out.ok, true);
  assert.equal(out.matches, 1);
  assert.equal(out.test_id, "cart-add");
  assert.equal(out.scope_matches, 1);
  assert.equal(out.page_matches, 2);
  assert.deepEqual(out.candidate, { test_id: "cart-add", matches: 1, role_name_matches: 1 });
  assert.equal(out.aria_snapshot_scope, "scope");
  assert.match(out.aria_snapshot, /button "Sepete ekle"/);
  assert.doesNotMatch(out.aria_snapshot, /Maden Suyu/); // yalnızca kapsayıcı
  assert.equal(out.http_status, 200);
  assert.ok(logins.includes("bayi1"));
});

test("kapsamsız yoklama: iki eşleşme → test_id yok (öneri insana)", async () => {
  const { out } = await probe({});
  assert.equal(out.matches, 2);
  assert.equal(out.test_id, null);
  assert.deepEqual(out.test_ids, ["cart-add", "cart-add"]);
  assert.equal(out.scope_matches, null);
  assert.equal(out.aria_snapshot_scope, "page");
});

test("eski testId adayı (add-to-cart) kapsamda 0 elemana çözülür", async () => {
  const { out } = await probe({ scope_test_id: "product-card-P-001", candidate_test_id: "add-to-cart" });
  assert.equal(out.matches, 1);
  assert.deepEqual(out.candidate, { test_id: "add-to-cart", matches: 0, role_name_matches: 0 });
});

test("yanlış rol + ad adayı: testId var ama rol + ad uymuyor", async () => {
  const { out } = await probe({
    scope_test_id: "product-card-P-001",
    candidate_test_id: "qty-input-P-001",
  });
  assert.deepEqual(out.candidate, { test_id: "qty-input-P-001", matches: 1, role_name_matches: 0 });
});

test("kapsayıcı yok: scope_matches 0, matches 0, sayfada yine 2", async () => {
  const { out } = await probe({ scope_test_id: "product-card-P-999" });
  assert.equal(out.scope_matches, 0);
  assert.equal(out.matches, 0);
  assert.equal(out.page_matches, 2);
});

test("giriş başarısız → çıkış 2 ve hata", async () => {
  const { code, out } = await probe({ login: { kullanici_adi: "bayi1", parola: "yanlis" } });
  assert.equal(code, 2);
  assert.equal(out.ok, false);
  assert.match(out.error, /giriş başarısız/);
});
