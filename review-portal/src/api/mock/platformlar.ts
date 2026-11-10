// 009 mobil-masaüstü örnek verisi: Android, iOS ve Windows için üretilmiş testler (PR + platform
// check'leri), uygulama ajanı adımları (app-mcp `app_*`, dikey ekran görüntüsü), platformlu CI koşuları
// ve hata anı sayfa kaynağı (Appium XML) kanıtlı bir triage kaydı + kimlik onarım önerisi.
// Yalnızca örnek veri (mock kipi); gerçek değerler core'dan gelir (specs/009-mobil-masaustu/plan.md §2.9).

import type { AjanAdimi, HataAnalizi, KosuDetay, ScriptDetay } from "../types";
import { uygulamaEkranGoruntusu } from "./ekran";
import { eslemeler, kosu, SAGLIK_OK, sonuc, t, TPD1_GOLDEN_CASELER, yerelGecti } from "./fixtures";

type UygulamaPlatformu = "android" | "ios" | "windows";

const E2E_APP = "demo-app/e2e-app/src/test/java/com/antreklabs/bayi";
const ETIKET: Record<UygulamaPlatformu, string> = { android: "Android", ios: "iOS", windows: "Windows" };

function adim(
  platform: UygulamaPlatformu,
  sira: number,
  step_id: string,
  arac: string,
  aciklama: string,
  po: string | null,
  method: string | null,
  args: unknown[],
  ekran: Parameters<typeof uygulamaEkranGoruntusu>[1],
  vurgu: string,
  sepet = 0,
): AjanAdimi {
  return {
    sira,
    step_id,
    arac,
    aciklama,
    po,
    method,
    args,
    verified: po ? true : null,
    ekran_goruntusu_url: uygulamaEkranGoruntusu(platform, ekran, vurgu, sepet),
    zaman: t(31, `09:${String(10 + sira).padStart(2, "0")}`),
    ham_cikti:
      arac === "app_launch"
        ? `- platform: ${platform}\n- uygulama: com.antreklabs.bayi (sıfırlandı)`
        : arac === "app_snapshot" || arac === "app_wait_for"
          ? `- ${platform === "windows" ? "Text" : "android.widget.TextView"} [id=${vurgu}]`
          : `- [id=${vurgu}] ${arac === "app_type" ? "yazıldı" : "dokunuldu"}`,
  };
}

/** C2 (7 adet kampanya) için uygulama ajanı adımları: app-mcp araçları, ekran nesnesi eşlemesi. */
export function uygulamaAdimlari(platform: UygulamaPlatformu): AjanAdimi[] {
  return [
    adim(platform, 1, "S1", "app_launch", `Uygulama başlatıldı (${ETIKET[platform]})`, null, null, [], "login", "login-username"),
    adim(platform, 2, "S1", "app_snapshot", "Giriş ekranı okundu", null, null, [], "login", "login-username"),
    adim(platform, 3, "S2", "app_type", "bayi1 ile giriş yapıldı", "GirisEkrani", "girisYap", ["bayi1", "Demo123!"], "login", "login-submit"),
    adim(platform, 4, "S3", "app_wait_for", "Katalog yüklendi", null, null, [], "catalog", "qty-input-P-001"),
    adim(platform, 5, "S3", "app_click", "P-001 adedi 7 girildi ve \"Sepete ekle\"ye dokunuldu", "KatalogEkrani", "sepeteEkle", ["P-001", 7], "catalog", "add-to-cart-P-001", 7),
    adim(platform, 6, "S4", "app_click", "Sepete gidildi", "KatalogEkrani", "sepetiAc", [], "cart", "cart-line-P-001", 7),
    adim(platform, 7, "S4", "app_generate_locator", "İndirim satırı kimliği üretildi: cart-discount", null, null, [], "cart", "cart-discount", 7),
    adim(platform, 8, "S4", "app_snapshot", "İndirim doğrulandı: 25,00 TL", "SepetEkrani", "dogrulaIndirim", ["25,00 TL"], "cart", "cart-discount", 7),
    adim(platform, 9, "S4", "app_snapshot", "Toplam doğrulandı: 150,00 TL", "SepetEkrani", "dogrulaToplam", ["150,00 TL"], "cart", "cart-total", 7),
  ];
}

const C2_KAYNAK = { "25,00 TL": "indirim 25,00 TL", "150,00 TL": "toplam 150,00 TL" };

function javaKodu(platform: UygulamaPlatformu, sinif: string): string {
  return `// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır.
// Case: TPD-1 C2 · Story: TPD-1 · Platform: ${platform}
// Eşleme: verify_and_map_app · mod: replay
package com.antreklabs.bayi.uretilen;

import com.antreklabs.bayi.altyapi.Bayi;
import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.annotations.Test;

@Bayi("bayi1")
public class ${sinif} extends TestTabani {
  @Test(groups = {"uretilen", "${platform}", "kampanya"}, description = "${TPD1_GOLDEN_CASELER[1].title}")
  public void senaryo() {
    // S2 — bayi1 ile giriş yapılır
    girisEkrani().girisYap("bayi1", "Demo123!");
    // S3 — Katalogda P-001 ürününden 7 adet sepete eklenir
    katalogEkrani().sepeteEkle("P-001", 7);
    // S4 — Sepet açılır
    katalogEkrani().sepetiAc();
    // Beklenen sonuç (değerler onaylı case metninden)
    sepetEkrani().dogrulaIndirim("25,00 TL");
    sepetEkrani().dogrulaToplam("150,00 TL");
  }
}
`;
}

function uygulamaScripti(
  platform: UygulamaPlatformu,
  id: string,
  prNo: number,
  check: { durum: "passed" | "failed" | "pending"; aciklama: string },
  olusturma: string,
): ScriptDetay {
  const kisa = { android: "a1d5e70c", ios: "b2e6f81d", windows: "c3f7a92e" }[platform];
  const sinif = `TPD1${ETIKET[platform].replace(/[^A-Za-z]/g, "")}C2_${kisa}Test`;
  const branch = `tp/case-${platform}-${kisa}`;
  const ci = check.durum;
  const adimlar = uygulamaAdimlari(platform);
  return {
    id,
    case_ids: ["case-1-2"],
    requirement_key: "TPD-1",
    baslik: TPD1_GOLDEN_CASELER[1].title,
    dosya_yolu: `${E2E_APP}/uretilen/${sinif}.java`,
    branch,
    platform,
    durum: "pr_open",
    pr: {
      number: prNo,
      url: null,
      baslik: `[TPD-1-C2 · ${platform}] ${TPD1_GOLDEN_CASELER[1].title} [AI-generated]`,
      branch,
      durum: "open",
      ci,
      icerik_hash: "",
      head_sha: "",
      checks: [{ ad: `local-ci-${platform}`, durum: check.durum, zorunlu: true, url: null, aciklama: check.aciklama }],
      forge: "local",
      dal: { geride: false, guncelleme: null, neden: null },
    },
    pass_at_1: true,
    zayif_test: false,
    break_verify: {
      durum: "not_started",
      asamalar: (["baseline", "broken", "restored"] as const).map((ad) => ({ ad, sonuc: "pending" as const, run_id: null, zaman: null })),
    },
    yerel_sinif: "gecti",
    mode: "replay",
    olusturma,
    hata: null,
    kod: javaKodu(platform, sinif),
    adimlar,
    eslemeler: eslemeler(adimlar, C2_KAYNAK).map((e) => ({ ...e, dogrulama_notu: null })),
    yerel_kontrol: { ...yerelGecti(""), run_id: null, tsc: null, eslint: null, aciklama: "javac ✓ · AST koruması ✓ · Appium 3/3 (cihazda)" },
    merge_engelleri: null,
    uyarilar: [],
    engel: null,
  };
}

/** Android (CI yeşil), iOS (CI sürüyor) ve Windows (CI kırmızı) PR'ları: aynı onaylı case, platform başına ayrı PR. */
export function uygulamaScriptleri(): ScriptDetay[] {
  return [
    uygulamaScripti("android", "scr-and", 21, { durum: "passed", aciklama: "javac ✓ · AST koruması ✓ · Appium 3/3 (emülatör)" }, t(31, "09:20")),
    uygulamaScripti("ios", "scr-ios", 22, { durum: "pending", aciklama: "Appium koşusu sürüyor (simülatör)" }, t(31, "09:35")),
    uygulamaScripti("windows", "scr-win", 23, { durum: "failed", aciklama: "javac ✓ · Appium 1/3 (NovaWindows): uygulama açılamadı" }, t(31, "09:50")),
  ];
}

// fixtures.ts ile döngüsel içe aktarma: modül yüklenirken değil, çağrıldığında okunur.
const testAndC2 = () => `TPD-1 C2 · ${TPD1_GOLDEN_CASELER[1].title} (Android)`;
const TEST_AND_GIRIS = "Bayi girişi · geçerli kullanıcıyla katalog açılır (Android, elle yazılmış)";

/** Hata anındaki Android sayfa kaynağı (Appium `getPageSource`): giriş düğmesinin kimliği değişmiş. */
export const ANDROID_SAYFA_KAYNAGI = `<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<hierarchy index="0" class="hierarchy" rotation="0" width="1080" height="2340">
  <android.widget.FrameLayout index="0" package="com.antreklabs.bayi" bounds="[0,0][1080,2340]">
    <android.view.ViewGroup index="0" resource-id="login-screen" bounds="[0,84][1080,2340]">
      <android.widget.TextView index="0" text="Bayi girişi" bounds="[60,300][1020,380]" />
      <android.widget.EditText index="1" resource-id="login-username" text="bayi1" bounds="[60,420][1020,540]" />
      <android.widget.EditText index="2" resource-id="login-password" text="••••••••" password="true" bounds="[60,580][1020,700]" />
      <android.widget.Button index="3" resource-id="login-button" text="Giriş yap" clickable="true" bounds="[60,760][1020,880]" />
    </android.view.ViewGroup>
  </android.widget.FrameLayout>
</hierarchy>
`;

/** UTF-8 metni `data:` adresine çevirir (örnek veride dosya sunucusu yok; görüntüleyici yerelde çözer). */
function dataAdresi(tur: string, metin: string): string {
  const b = new TextEncoder().encode(metin);
  let ikili = "";
  for (const x of b) ikili += String.fromCharCode(x);
  return `data:${tur};base64,${btoa(ikili)}`;
}

/** Android CI koşusu (gece, main): C2 yeşil, elle yazılmış giriş testi kimlik değişikliğiyle kırmızı. */
export function uygulamaKosulari(): KosuDetay[] {
  return [
    kosu(
      "run-110",
      "nightly",
      "local",
      t(28, "18:00"),
      [
        sonuc("r110-1", testAndC2(), "passed", 41000, { case_id: "case-1-2" }),
        sonuc("r110-2", TEST_AND_GIRIS, "failed", 38000, {
          hata_mesaji: "NoSuchElementException: An element could not be located on the page using the given search parameters (id=login-submit)",
          failure_id: "fail-5",
          triage_sinifi: "test_maintenance",
          triage_alt_tur: "locator",
        }),
      ],
      {
        commit: "a1d5e70",
        platform: "android",
        platform_kontrolleri: [{ ad: "local-ci-android", platform: "android", durum: "failed" }],
      },
    ),
  ];
}

export function uygulamaHatalari(): HataAnalizi[] {
  return [
    {
      id: "fail-5",
      run_id: "run-110",
      test_adi: TEST_AND_GIRIS,
      hata_imzasi: "locator:id(login-submit):NoSuchElement",
      hata_mesaji: "NoSuchElementException: id=login-submit",
      sinif: "test_maintenance",
      alt_tur: "locator",
      kural: "test_maintenance/locator",
      platform: "android",
      eslesen_sinyaller: [
        { kod: "health_ok", aciklama: "Koşu öncesi cihaz ve uygulama sağlıklı (emülatör açık, uygulama yüklü)", kaynak: "saglik", kanit: "appium 200 · api 200" },
        { kod: "eski_kimlik_ekranda_yok", aciklama: "Kimlik 'login-submit' hata anındaki ekranda yok ('login-screen' kapsayıcısı ekranda)", kaynak: "sayfa-kaynagi.xml", kanit: null },
        { kod: "test_id_farkli", aciklama: "Kimlik değişmiş: 'login-submit' → 'login-button' (ekranda tek aday, sembol tablosunda tanımsız)", kaynak: "sayfa-kaynagi.xml", kanit: '<android.widget.Button resource-id="login-button" text="Giriş yap" />' },
      ],
      karar_kaynagi: "rule",
      llm_yorumu: null,
      oneri: {
        tur: "locator_fix",
        dosya: `${E2E_APP}/ekranlar/Kimlikler.java`,
        anahtar: "Giris.GIRIS_YAP",
        eski_test_id: "login-submit",
        yeni_test_id: "login-button",
        // Uygulama önerisinde rol/ad/url_path yoktur (core boş gönderir); portal satırı çizmez.
        rol: "",
        ad: "",
        within: null,
        scope_test_id: "login-screen",
        kaynak: "sayfa_kaynagi",
        platform: "android",
        dogrulama: [
          "Kimlik 'login-submit' hata anındaki ekranda yok",
          "Ekranda tek aday kimlik: login-button (sembol tablosunda tanımsız)",
        ],
        aria_dogrulama: null,
        ast_guard: null,
        yerel_kontrol: null,
        etkilenen_testler: [{ test_adi: TEST_AND_GIRIS, durum: null }, { test_adi: testAndC2(), durum: null }],
        degisen_dosyalar: [],
        yama: null,
        neden: null,
        durum: "proposed",
        pr: null,
      },
      kanit: {
        hata_mesaji:
          "org.openqa.selenium.NoSuchElementException: An element could not be located on the page using the given search parameters.\n  Kimlik: login-submit (Kimlikler.Giris.GIRIS_YAP)\n  at GirisEkrani.girisYap(GirisEkrani.java:20)",
        beklenen: null,
        gerceklesen: null,
        konum: "ekranlar/GirisEkrani.java:20",
        aria_snippet: null,
        locator_probe: null,
        saglik: SAGLIK_OK,
      },
      kanit_linkleri: [
        { etiket: "Ekran görüntüsü", url: uygulamaEkranGoruntusu("android", "login", "login-submit"), tur: "screenshot" },
        { etiket: "Hata anı sayfa kaynağı (Appium)", url: dataAdresi("application/xml", ANDROID_SAYFA_KAYNAGI), tur: "page_source" },
      ],
      mode: null,
      zaman: t(28, "18:04"),
    },
  ];
}

// ------------------------------------------------------------------ mock kod üretimi (uygulama platformu)

const PO_JAVA: Record<string, { sinif: string; erisimci: string; sayfa: "login" | "catalog" | "cart" }> = {
  LoginPage: { sinif: "GirisEkrani", erisimci: "girisEkrani", sayfa: "login" },
  CatalogPage: { sinif: "KatalogEkrani", erisimci: "katalogEkrani", sayfa: "catalog" },
  CartPage: { sinif: "SepetEkrani", erisimci: "sepetEkrani", sayfa: "cart" },
};
const METOT_JAVA: Record<string, string> = {
  goto: "ac",
  login: "girisYap",
  addToCart: "sepeteEkle",
  openCart: "sepetiAc",
  expectCartCount: "dogrulaSepetSayaci",
  expectSubtotal: "dogrulaAraToplam",
  expectDiscount: "dogrulaIndirim",
  expectTotal: "dogrulaToplam",
  expectFreeQuantity: "dogrulaBedavaAdet",
  expectMinOrderWarning: "dogrulaMinimumTutarUyarisi",
  expectCheckoutDisabled: "dogrulaOnayPasif",
};
const ARAC_APP: Record<string, string> = {
  browser_navigate: "app_wait_for",
  browser_type: "app_type",
  browser_click: "app_click",
  browser_snapshot: "app_snapshot",
};

/**
 * Web golden adımlarını uygulama ajanı adımlarına çevirir (yalnız örnek veri): önce `app_launch`,
 * araçlar `app_*`, page object → Java ekran nesnesi, ekran görüntüsü platformun ekranı.
 */
export function uygulamayaCevir(adimlar: AjanAdimi[], platform: UygulamaPlatformu): AjanAdimi[] {
  const ilk = adimlar[0];
  const baslat: AjanAdimi = {
    ...(ilk ?? { step_id: "S1", args: [], verified: null, zaman: t(31, "09:00") }),
    sira: 1,
    step_id: "S1",
    arac: "app_launch",
    aciklama: `Uygulama başlatıldı (${ETIKET[platform]})`,
    po: null,
    method: null,
    args: [],
    verified: null,
    ekran_goruntusu_url: uygulamaEkranGoruntusu(platform, "login", "login-username"),
    ham_cikti: `- platform: ${platform}\n- uygulama: com.antreklabs.bayi (sıfırlandı)`,
    zaman: ilk?.zaman ?? t(31, "09:00"),
  };
  return [
    baslat,
    ...adimlar.map((a, i) => {
      const po = a.po ? PO_JAVA[a.po] : undefined;
      const sepet = typeof a.args[1] === "number" ? (a.args[1] as number) : 0;
      return {
        ...a,
        sira: i + 2,
        arac: ARAC_APP[a.arac] ?? a.arac,
        po: po?.sinif ?? a.po,
        method: a.method ? (METOT_JAVA[a.method] ?? a.method) : null,
        ekran_goruntusu_url: uygulamaEkranGoruntusu(platform, po?.sayfa ?? "catalog", "", sepet),
        ham_cikti: `- [${platform}] ${a.aciklama}`,
      };
    }),
  ];
}

/** Eşlemeden şablonla Java testi (009 §2.8 biçimi; yalnız örnek veri). */
export function javaTestKodu(platform: UygulamaPlatformu, sinif: string, baslik: string, adimlar: AjanAdimi[]): string {
  const govde = adimlar
    .filter((a) => a.po && a.method)
    .map((a) => {
      const erisimci = Object.values(PO_JAVA).find((x) => x.sinif === a.po)?.erisimci ?? "ekran";
      const args = a.args.map((x) => JSON.stringify(x)).join(", ");
      return `    // ${a.step_id} — ${a.aciklama}\n    ${erisimci}().${a.method}(${args});`;
    })
    .join("\n");
  return `// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır.
// Platform: ${platform}
package com.antreklabs.bayi.uretilen;

import com.antreklabs.bayi.altyapi.Bayi;
import com.antreklabs.bayi.altyapi.TestTabani;
import org.testng.annotations.Test;

@Bayi("bayi1")
public class ${sinif} extends TestTabani {
  @Test(groups = {"uretilen", "${platform}"}, description = ${JSON.stringify(baslik)})
  public void senaryo() {
${govde}
  }
}
`;
}

/** Üretilen Java dosyasının e2e-app köküne göre yolu (009 §2.9). */
export function javaDosyaYolu(platform: UygulamaPlatformu, story: string, siraNo: number, kisa: string): { yol: string; sinif: string } {
  const sinif = `${story.replace(/[^A-Za-z0-9]/g, "")}${ETIKET[platform].replace(/[^A-Za-z]/g, "")}C${siraNo}_${kisa}Test`;
  return { yol: `${E2E_APP}/uretilen/${sinif}.java`, sinif };
}
