// 014 test dilleri örnek verisi: müşteri CI hattı (Android Kotlin/Espresso, iOS Swift/XCUITest). TP üretir +
// statik koruma (tree-sitter) + PR; derleme ve koşu müşterinin GitHub Actions iş akışında, sonuç check'ten ve
// `tp-results` artefaktından okunur; kırarak doğrulama yok (aip-review/test-dilleri/TASARIM.md §3.3–3.4).
// Yalnızca örnek veri (mock `diller-acik` senaryosu); gerçek değerler core `musteri_ci`'den (Ş5) gelir.

import type { ScriptDetay } from "../types";
import { eslemeler, t, TPD1_GOLDEN_CASELER } from "./fixtures";
import { ANDROID_DEPOSU, uygulamaAdimlari } from "./platformlar";

const C2_KAYNAK = { "25,00 TL": "indirim 25,00 TL", "150,00 TL": "toplam 150,00 TL" };

const KOTLIN_KODU = `// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır. Koşu müşteri CI'da (mobil-android-kotlin); kırarak doğrulanmadı.
package com.antreklabs.bayi.tp.uretilen

import androidx.test.ext.junit.rules.ActivityScenarioRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.antreklabs.bayi.MainActivity
import com.antreklabs.bayi.tp.ekranlar.GirisEkrani
import com.antreklabs.bayi.tp.ekranlar.KatalogEkrani
import com.antreklabs.bayi.tp.ekranlar.SepetEkrani
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class TPD1AndroidC2_a1d5e70cTest {
    @get:Rule
    val senaryo = ActivityScenarioRule(MainActivity::class.java)

    @Test
    fun senaryo() {
        // S2 — bayi1 ile giriş yap
        GirisEkrani().girisYap("bayi1", "Demo123!")
        // S3 — P-001 adedini 7 gir ve sepete ekle
        KatalogEkrani().sepeteEkle("P-001", 7)
        KatalogEkrani().sepetiAc()
        // Beklenen sonuç
        SepetEkrani().dogrulaIndirim("25,00 TL")
        SepetEkrani().dogrulaToplam("150,00 TL")
    }
}
`;

const SWIFT_KODU = `// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır. Koşu müşteri CI'da (mobil-ios-swift); kırarak doğrulanmadı.
import XCTest

final class TPD1IosC2_b2e6f81dTests: XCTestCase {
    @MainActor
    func testSenaryo() throws {
        let app = XCUIApplication()
        app.launch()
        // S2 — bayi1 ile giriş yap
        GirisEkrani(app: app).girisYap(kullanici: "bayi1", sifre: "Demo123!")
        // S3 — P-001 adedini 7 gir ve sepete ekle
        KatalogEkrani(app: app).sepeteEkle(urun: "P-001", adet: 7)
        KatalogEkrani(app: app).sepetiAc()
        // Beklenen sonuç
        SepetEkrani(app: app).dogrulaIndirim("25,00 TL")
        SepetEkrani(app: app).dogrulaToplam("150,00 TL")
    }
}
`;

const KIRMA_YOK: ScriptDetay["break_verify"] = {
  durum: "not_started",
  asamalar: (["baseline", "broken", "restored"] as const).map((ad) => ({ ad, sonuc: "pending" as const, run_id: null, zaman: null })),
};

function yerelKoruma(): ScriptDetay["yerel_kontrol"] {
  // Müşteri CI hattında TP yalnız statik korumayı koşar (tree-sitter guard); koşu müşteri CI'da.
  return {
    tsc: null,
    eslint: null,
    ast_guard: null,
    adimlar: [{ ad: "guard", durum: "passed" }],
    tekrar: 0,
    sonuc: null,
    sinif: null,
    aciklama: null,
    run_id: null,
    duzeltme_turu: 0,
    basarisiz: [],
    gecen: null,
    toplam: null,
    hata: null,
  };
}

/**
 * Android Kotlin (kurulum PR'ı birleşti, müşteri CI yeşil, 1/1 geçti) ve iOS Swift (kurulum PR'ı açık,
 * UI test hedefi elle eklenecek; müşteri CI koşuyor).
 */
export function musteriCiScriptleri(): ScriptDetay[] {
  const ortak = {
    case_ids: ["case-1-2"],
    requirement_key: "TPD-1",
    baslik: TPD1_GOLDEN_CASELER[1].title,
    durum: "pr_open" as const,
    dil_kaynagi: "secildi" as const,
    dogrulanmamis: false,
    hat: "musteri_ci" as const,
    pass_at_1: null,
    zayif_test: false,
    break_verify: KIRMA_YOK,
    yerel_sinif: null,
    mode: "replay" as const,
    hata: null,
    merge_engelleri: null,
    uyarilar: [],
    engel: null,
  };
  const androidAdimlari = uygulamaAdimlari("android");
  const iosAdimlari = uygulamaAdimlari("ios");
  const ktDal = "tp/case-android-kotlin-a1d5e70c";
  const swDal = "tp/case-ios-swift-b2e6f81d";
  return [
    {
      ...ortak,
      id: "scr-kt",
      platform: "android",
      depo: ANDROID_DEPOSU,
      depo_adi: ANDROID_DEPOSU,
      dil: "kotlin",
      dosya_yolu: "app/src/androidTest/java/com/antreklabs/bayi/tp/uretilen/TPD1AndroidC2_a1d5e70cTest.kt",
      branch: ktDal,
      pr: {
        depo: ANDROID_DEPOSU,
        depo_adi: ANDROID_DEPOSU,
        number: 42,
        url: `https://github.com/${ANDROID_DEPOSU}/pull/42`,
        baslik: `[TPD-1-C2 · android · Kotlin] ${TPD1_GOLDEN_CASELER[1].title} [AI-generated]`,
        branch: ktDal,
        durum: "open",
        ci: "passed",
        icerik_hash: "",
        head_sha: "9f3c1a7e2b",
        checks: [{ ad: "mobil-android-kotlin", durum: "passed", zorunlu: true, url: null, aciklama: "Espresso 1/1 (müşteri CI, emülatör API 34)" }],
        forge: "github",
        dal: { geride: false, guncelleme: null, neden: null },
      },
      olusturma: t(31, "11:10"),
      kod: KOTLIN_KODU,
      adimlar: androidAdimlari,
      eslemeler: eslemeler(androidAdimlari, C2_KAYNAK).map((e) => ({ ...e, dogrulama_notu: null })),
      yerel_kontrol: yerelKoruma(),
      musteri_ci: {
        check_adi: "mobil-android-kotlin",
        saglayici: "github_actions",
        durum: "gecti",
        head_sha: "9f3c1a7e2b",
        run_url: `https://github.com/${ANDROID_DEPOSU}/actions/runs/1180042`,
        tamamlanma: t(31, "11:24"),
        sonuc: { toplam: 1, gecen: 1, kalan: 0, atlanan: 0 },
        artefakt: "alindi",
        neden: null,
      },
      kurulum: { durum: "birlesti", number: 40, url: `https://github.com/${ANDROID_DEPOSU}/pull/40`, baslik: "TP kurulum: Espresso iskeleti", eksikler: [], elle_adimlar: [] },
    },
    {
      ...ortak,
      id: "scr-sw",
      platform: "ios",
      dil: "swift",
      dosya_yolu: "demo-app/mobile/ios/BayiSiparisUITests/Uretilen/TPD1IosC2_b2e6f81dTests.swift",
      branch: swDal,
      pr: {
        number: 43,
        url: "https://github.com/antreklabs/bayi-siparis/pull/43",
        baslik: `[TPD-1-C2 · ios · Swift] ${TPD1_GOLDEN_CASELER[1].title} [AI-generated]`,
        branch: swDal,
        durum: "open",
        ci: "pending",
        icerik_hash: "",
        head_sha: "4d2e8b0c11",
        checks: [{ ad: "mobil-ios-swift", durum: "pending", zorunlu: true, url: null, aciklama: "XCUITest koşuyor (müşteri CI, macOS)" }],
        forge: "github",
        dal: { geride: false, guncelleme: null, neden: null },
      },
      olusturma: t(31, "11:30"),
      kod: SWIFT_KODU,
      adimlar: iosAdimlari,
      eslemeler: eslemeler(iosAdimlari, C2_KAYNAK).map((e) => ({ ...e, dogrulama_notu: null })),
      yerel_kontrol: yerelKoruma(),
      musteri_ci: {
        check_adi: "mobil-ios-swift",
        saglayici: "github_actions",
        durum: "kosuyor",
        head_sha: "4d2e8b0c11",
        run_url: "https://github.com/antreklabs/bayi-siparis/actions/runs/1180057",
        tamamlanma: null,
        sonuc: null,
        artefakt: "bekliyor",
        neden: null,
      },
      kurulum: {
        durum: "acik",
        number: 41,
        url: "https://github.com/antreklabs/bayi-siparis/pull/41",
        baslik: "TP kurulum: XCUITest iskeleti ve mobil-ios-swift iş akışı",
        eksikler: ["XCUITest ekran nesnesi kütüphanesi", "mobil-ios-swift iş akışı (GitHub Actions)"],
        elle_adimlar: ["Xcode'da eşitlenmiş klasörlü (synchronized folder) bir UI Testing Bundle hedefi ekleyin: BayiSiparisUITests"],
      },
    },
  ];
}
