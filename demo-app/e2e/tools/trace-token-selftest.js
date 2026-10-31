// Güvenlik öz sınaması (npm run selftest:trace-token): DEMOAPP_TEST_TOKEN kırmızı koşunun
// artefaktlarına (trace.zip, ekran görüntüsü, rapor) sızmamalıdır. Bu dosyalar koşu artefaktı
// olarak core'dan her role servis edilir; token yalnızca demo-app-api ve test-runner'da bulunur.
//
// Bilinen bir token ve BREAK_CAMPAIGN=1 ile (fikstür /test/reset + /test/break çağırır) bir kırmızı
// ve bir yeşil test, her testte trace açıkken koşar; ardından çıktı dizinindeki her dosya (zip
// içerikleri açılarak) token için taranır. Uygulama webServer ile başlatılır (BASE_URL verilirse
// çalışan ortama karşı; o durumda DEMO_API_URL + DEMOAPP_TEST_TOKEN dışarıdan gelir).
import console from "node:console";
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { join, relative } from "node:path";
import process from "node:process";
import { URL, fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const out = join(root, "results", "trace-selftest");
const token = process.env.DEMOAPP_TEST_TOKEN ?? `izsiz-${randomBytes(16).toString("hex")}`;

rmSync(out, { recursive: true, force: true });
const run = spawnSync(
  "npx",
  ["--no-install", "playwright", "test", "--config", "tools/trace-selftest/playwright.config.ts", "--retries=0"],
  {
    cwd: root,
    stdio: "inherit",
    env: {
      ...process.env,
      DEMOAPP_TEST_TOKEN: token,
      BREAK_CAMPAIGN: "1",
      DEMO_API_PORT: process.env.DEMO_API_PORT ?? "18100",
      DEMO_WEB_PREVIEW_PORT: process.env.DEMO_WEB_PREVIEW_PORT ?? "18181",
    },
  },
);

const fail = (msg) => {
  console.error(`HATA: ${msg}`);
  process.exit(1);
};

const report = JSON.parse(readFileSync(join(out, "results.json"), "utf8"));
const statuses = [];
const walk = (s) => {
  for (const sp of s.specs ?? []) for (const t of sp.tests) for (const r of t.results) statuses.push([sp.title, r.status]);
  (s.suites ?? []).forEach(walk);
};
report.suites.forEach(walk);
const red = statuses.filter(([, st]) => st === "failed" || st === "timedOut");
const green = statuses.filter(([, st]) => st === "passed");
if (run.status === 0 || red.length !== 1 || green.length !== 1) {
  fail(`beklenen 1 kırmızı + 1 yeşil test; bulunan: ${JSON.stringify(statuses)} (çıkış ${run.status})`);
}

function files(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? files(join(dir, e.name)) : [join(dir, e.name)],
  );
}

/** Dosyanın taranacak içeriği: zip ise tüm girdileri açılmış hâliyle (`unzip -p`). */
function contents(file) {
  if (!file.endsWith(".zip")) return readFileSync(file);
  const r = spawnSync("unzip", ["-p", file], { maxBuffer: 512 * 1024 * 1024 });
  if (r.status !== 0) fail(`${file} açılamadı (unzip gerekli): ${r.stderr}`);
  return r.stdout;
}

const all = existsSync(out) ? files(out) : [];
const traces = all.filter((f) => f.endsWith("trace.zip"));
if (traces.length < 2) fail(`her test için trace.zip beklenirdi; bulunan: ${traces.length}`);
let sawNetwork = false;
const leaks = [];
for (const f of all) {
  const text = contents(f).toString("latin1");
  if (text.includes(token)) leaks.push(relative(root, f));
  if (f.endsWith("trace.zip") && text.includes("/api/auth/login")) sawNetwork = true;
}
// Tarama boş geçmesin: trace'ler fikstürün izlenen istek trafiğini (API ile giriş) içermeli.
if (!sawNetwork) fail("trace'lerde /api/auth/login isteği yok; tarama anlamsız (trace ağ kaydı alınmamış)");
if (leaks.length) fail(`DEMOAPP_TEST_TOKEN artefaktlara sızdı:\n  ${leaks.join("\n  ")}`);
console.log(`ok  ${all.length} dosya (${traces.length} trace.zip) tarandı; token yok, kırmızı test: ${red[0][0]}`);
console.log("Trace token öz sınaması: tamam");
