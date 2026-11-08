#!/usr/bin/env node
// Erişilebilirlik kimliği sözleşmesi denetimi (specs/009-mobil-masaustu/plan.md §2.2).
//
// Tek liste: demo-app/kimlikler.json — web kaynağındaki (demo-app/web/src) data-testid değerlerinden
// üretilir. Bu betik:
//   1. web kaynağını tarar ve listeyi yeniden üretir; dosyadakiyle aynı değilse HATA (web değişti,
//      `npm run kimlik-uret` ile liste güncellenmeli ve mobil/masaüstü uygulamaları uyarlanmalı);
//   2. e2e locator'larındaki (demo-app/e2e/pages/**/locators.ts) her testId'nin listede olduğunu;
//   3. mobil kaynağın (src/**) listedeki HER kimliği, doğru ekran dosyasında kullandığını ve listede
//      OLMAYAN kimlik kullanmadığını denetler.
// Önek kimlikler (sonu `-`; ör. `product-card-`) dinamik kimliklerdir: web'de
// data-testid={`product-card-${p.kod}`}, mobilde {...tid(`product-card-${p.kod}`)}.
//
// Kullanım: node scripts/kimlik-kontrol.mjs          → denetim (≠0 = ihlal)
//           node scripts/kimlik-kontrol.mjs --uret   → kimlikler.json'u web kaynağından yazar
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const MOBIL = join(dirname(fileURLToPath(import.meta.url)), "..");
const DEMO = join(MOBIL, "..");
const LISTE = join(DEMO, "kimlikler.json");
const WEB_SRC = join(DEMO, "web", "src");
const E2E_PAGES = join(DEMO, "e2e", "pages");
const MOBIL_SRC = join(MOBIL, "src");

// Web dosyası → ekran adı. Yeni bir web sayfası eklenirse burada eşlenmeli (aksi halde HATA).
const WEB_EKRAN = {
  "components/Layout.tsx": "ortak",
  "pages/LoginPage.tsx": "giris",
  "pages/CatalogPage.tsx": "katalog",
  "pages/CartPage.tsx": "sepet",
  "pages/OrderConfirmationPage.tsx": "siparis-onay",
  "pages/OrdersPage.tsx": "siparisler",
};

// Ekran adı → kimliğin kullanılması gereken mobil dosya.
const MOBIL_EKRAN = {
  ortak: "bilesenler/Kabuk.tsx",
  giris: "ekranlar/GirisEkrani.tsx",
  katalog: "ekranlar/KatalogEkrani.tsx",
  sepet: "ekranlar/SepetEkrani.tsx",
  "siparis-onay": "ekranlar/OnayEkrani.tsx",
  siparisler: "ekranlar/SiparislerEkrani.tsx",
};

function dosyalar(kok, uzantilar) {
  const sonuc = [];
  for (const ad of readdirSync(kok)) {
    const yol = join(kok, ad);
    if (statSync(yol).isDirectory()) sonuc.push(...dosyalar(yol, uzantilar));
    else if (uzantilar.some((u) => ad.endsWith(u))) sonuc.push(yol);
  }
  return sonuc.sort();
}

const goreli = (kok, yol) => relative(kok, yol).split(sep).join("/");

/**
 * Bir kimlik ifadesini çözer: "x" / 'x' → sabit; `x-${…}` → önek "x-".
 * Dönüş: { id, onek } ya da { hata }.
 */
function coz(tirnak, govde) {
  if (tirnak !== "`") return { id: govde, onek: false };
  const i = govde.indexOf("${");
  if (i < 0) return { id: govde, onek: false };
  const onek = govde.slice(0, i);
  if (!onek.endsWith("-") || govde.indexOf("${", i + 2) >= 0 || !govde.endsWith("}")) {
    return { hata: `dinamik kimlik yalnızca \`<önek->\${…}\` biçiminde olabilir: \`${govde}\`` };
  }
  return { id: onek, onek: true };
}

/** Tırnaklı ifade (', ", `): `n` = tırnak grubunun numarası (geri başvuru için). */
const ifade = (n) => "([\"'`])((?:(?!\\" + n + ")[^\\\\])*)\\" + n;

/** Yorumları atar (doküman örnekleri kimlik kullanımı sayılmasın); `://` korunur. */
const yorumsuz = (metin) => metin.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

function webKimlikleri(hatalar) {
  const re = new RegExp(String.raw`data-testid=(?:\{\s*${ifade(1)}\s*\}|${ifade(3)})`, "g");
  const harita = new Map();
  for (const yol of dosyalar(WEB_SRC, [".tsx", ".ts"])) {
    const g = goreli(WEB_SRC, yol);
    const metin = yorumsuz(readFileSync(yol, "utf8"));
    for (const m of metin.matchAll(re)) {
      const r = coz(m[1] ?? m[3], m[2] ?? m[4]);
      if (r.hata) {
        hatalar.push(`web ${g}: ${r.hata}`);
        continue;
      }
      const ekran = WEB_EKRAN[g];
      if (!ekran) {
        hatalar.push(`web ${g}: ekran eşlemesi yok (kimlik-kontrol.mjs WEB_EKRAN'a ekleyin)`);
        continue;
      }
      const onceki = harita.get(r.id);
      if (onceki && onceki.ekran !== ekran) {
        hatalar.push(`web: "${r.id}" iki ekranda (${onceki.ekran}, ${ekran})`);
      }
      harita.set(r.id, { id: r.id, ekran, onek: r.onek });
    }
  }
  return [...harita.values()].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

function listeBelgesi(kimlikler) {
  return {
    $aciklama:
      "Erişilebilirlik kimliği sözleşmesi (specs/009-mobil-masaustu/plan.md §2.2). Web data-testid " +
      "değerlerinden üretilir: `cd demo-app/mobile && npm run kimlik-uret`. Elle düzenlemeyin. " +
      "onek=true: kimlik önektir, sonuna ürün kodu / sipariş numarası eklenir (product-card-P-001). " +
      "iOS: accessibilityIdentifier, Android: resource-id, Windows: AutomationId.",
    kaynak: "demo-app/web/src (data-testid)",
    kimlikler,
  };
}

function e2eKimlikleri() {
  const sonuc = [];
  for (const yol of dosyalar(E2E_PAGES, ["locators.ts"])) {
    const metin = readFileSync(yol, "utf8");
    for (const m of metin.matchAll(/testId:\s*"([^"]+)"/g)) sonuc.push({ id: m[1], dosya: goreli(DEMO, yol) });
  }
  return sonuc;
}

function mobilKimlikleri(hatalar) {
  const tidRe = new RegExp(String.raw`\btid\(\s*${ifade(1)}\s*\)`, "g");
  // Kimlikler yalnızca tid() ile verilir; testID'ye doğrudan literal yazmak denetimi atlatır.
  const hamRe = /\btestID=\s*(?:"|'|\{\s*["'`])/g;
  const kullanim = new Map(); // id → Set(dosya)
  for (const yol of dosyalar(MOBIL_SRC, [".tsx", ".ts"])) {
    const g = goreli(MOBIL_SRC, yol);
    const metin = yorumsuz(readFileSync(yol, "utf8"));
    for (const m of metin.matchAll(hamRe)) {
      const satir = metin.slice(0, m.index).split("\n").length;
      hatalar.push(`mobil ${g}:${satir}: testID'ye literal yazılmış; {...tid("…")} kullanın`);
    }
    for (const m of metin.matchAll(tidRe)) {
      const r = coz(m[1], m[2]);
      if (r.hata) {
        hatalar.push(`mobil ${g}: ${r.hata}`);
        continue;
      }
      if (!kullanim.has(r.id)) kullanim.set(r.id, { onek: r.onek, dosyalar: new Set() });
      kullanim.get(r.id).dosyalar.add(g);
    }
  }
  return kullanim;
}

function main() {
  const hatalar = [];
  const web = webKimlikleri(hatalar);
  const beklenen = listeBelgesi(web);

  if (process.argv.includes("--uret")) {
    if (hatalar.length) {
      for (const h of hatalar) console.error(`HATA: ${h}`);
      process.exit(1);
    }
    writeFileSync(LISTE, `${JSON.stringify(beklenen, null, 2)}\n`);
    console.log(`kimlikler.json yazıldı: ${web.length} kimlik`);
    return;
  }

  // 1. Liste web kaynağıyla aynı mı?
  let dosya;
  try {
    dosya = JSON.parse(readFileSync(LISTE, "utf8"));
  } catch (e) {
    hatalar.push(`demo-app/kimlikler.json okunamadı: ${e.message}`);
  }
  if (dosya && JSON.stringify(dosya) !== JSON.stringify(beklenen)) {
    const eski = new Set((dosya.kimlikler ?? []).map((k) => `${k.id}|${k.ekran}|${k.onek}`));
    const yeni = new Set(web.map((k) => `${k.id}|${k.ekran}|${k.onek}`));
    const eksik = [...yeni].filter((k) => !eski.has(k));
    const fazla = [...eski].filter((k) => !yeni.has(k));
    hatalar.push(
      "demo-app/kimlikler.json web kaynağıyla uyuşmuyor (`npm run kimlik-uret`)" +
        (eksik.length ? `; listede yok: ${eksik.join(", ")}` : "") +
        (fazla.length ? `; web'de yok: ${fazla.join(", ")}` : ""),
    );
  }

  // 2. e2e locator'ları listede mi?
  const ids = new Map(web.map((k) => [k.id, k]));
  for (const { id, dosya: d } of e2eKimlikleri()) {
    if (!ids.has(id)) hatalar.push(`e2e ${d}: "${id}" web kaynağında yok`);
  }

  // 3. Mobil kaynak listeyle birebir mi?
  const mobil = mobilKimlikleri(hatalar);
  for (const k of web) {
    const m = mobil.get(k.id);
    const hedef = MOBIL_EKRAN[k.ekran];
    if (!m) {
      hatalar.push(`mobil: "${k.id}" (${k.ekran}) kullanılmıyor`);
      continue;
    }
    if (m.onek !== k.onek) {
      hatalar.push(`mobil: "${k.id}" ${k.onek ? "önek (dinamik) olmalı" : "sabit olmalı, önek değil"}`);
    }
    if (!m.dosyalar.has(hedef)) {
      hatalar.push(`mobil: "${k.id}" ${hedef} içinde olmalı (bulunduğu: ${[...m.dosyalar].join(", ")})`);
    }
  }
  for (const [id, m] of mobil) {
    if (!ids.has(id)) hatalar.push(`mobil: "${id}" listede yok (${[...m.dosyalar].join(", ")})`);
  }

  if (hatalar.length) {
    for (const h of hatalar) console.error(`HATA: ${h}`);
    console.error(`kimlik-kontrol: ${hatalar.length} ihlal`);
    process.exit(1);
  }
  console.log(`kimlik-kontrol: tamam — ${web.length} kimlik (web = liste = mobil; e2e locator'ları listede)`);
}

main();
