// Üretim seçenekleri (011 K5) ve derinleştirme (P5/P6) saf yardımcıları.
import { describe, expect, it } from "vitest";
import { derinlestirmeDurumuUyarla, derinlestirmeEngeli, derinlestirmeSonucu } from "./derinlestirme";
import {
  alanGorunur,
  baslangicSecenekleri,
  derinlestirmeReplayAdi,
  EK_BILGI_ALANLARI,
  gorunurAlanlar,
  platformDegistir,
  platformReplayAdi,
  secenekGovdesiMi,
  secenekHatalari,
  seceneklerUyarla,
  standartEkle,
  standartSil,
  uretimGovdesi,
  uretimSecenekleriYanitiUyarla,
  varsayilanSecenekler,
} from "./uretimSecenekleri";

const alanAdlari = (platformlar: string[], ek: Record<string, string | boolean> = {}) =>
  gorunurAlanlar(EK_BILGI_ALANLARI, { platformlar, ek_bilgi: ek }).map(([ad]) => ad);

describe("varsayılan ve uyarlama", () => {
  it("varsayılan: platformsuz, SYSTEM, boş listeler", () => {
    expect(varsayilanSecenekler()).toEqual({ platformlar: [], test_seviyesi: "SYSTEM", benimsenen_standartlar: [], kapsam_disi: "", roller: "", ek_bilgi: {} });
  });

  it("eksik/yanlış tipli alanlar varsayılana düşer; ek bilgide yalnız metin ve evet/hayır kalır", () => {
    const s = seceneklerUyarla({ platformlar: ["Web", "Web", 3], test_seviyesi: "", roller: 5, ek_bilgi: { tarayicilar: "Chrome", api_sozlesmesi_var: true, x: 1 } });
    expect(s).toEqual({ platformlar: ["Web"], test_seviyesi: "SYSTEM", benimsenen_standartlar: [], kapsam_disi: "", roller: "", ek_bilgi: { tarayicilar: "Chrome", api_sozlesmesi_var: true } });
    expect(seceneklerUyarla(null)).toEqual(varsayilanSecenekler());
  });

  it("yanıt: kayıtlı seçenek varsa ön dolum o, yoksa varsayılan; katalog yoksa yerel kopya", () => {
    const y = uretimSecenekleriYanitiUyarla({
      secenekler: { platformlar: ["API"], test_seviyesi: "INTEGRATION", benimsenen_standartlar: ["OWASP API Top 10"], kapsam_disi: "x", roller: "r", ek_bilgi: {} },
      varsayilan: varsayilanSecenekler(),
      platformlar: ["Web", "API"],
      test_seviyeleri: ["SYSTEM", "INTEGRATION"],
      ek_bilgi_alanlari: { auth_tipi: { etiket: "Kimlik doğrulama tipi", tur: "metin", platformlar: ["API"] } },
    });
    expect(baslangicSecenekleri(y).platformlar).toEqual(["API"]);
    expect(baslangicSecenekleri(y).test_seviyesi).toBe("INTEGRATION");
    expect(Object.keys(y.ek_bilgi_alanlari)).toEqual(["auth_tipi"]);

    const bos = uretimSecenekleriYanitiUyarla({ secenekler: null, varsayilan: { test_seviyesi: "E2E" } });
    expect(baslangicSecenekleri(bos)).toMatchObject({ platformlar: [], test_seviyesi: "E2E" });
    expect(bos.platformlar).toContain("Desktop-Linux");
    expect(bos.ek_bilgi_alanlari).toEqual(EK_BILGI_ALANLARI);
  });
});

describe("alan görünürlüğü", () => {
  it("platform yokken hiçbir alan görünmez; otomasyon aracı her platformda", () => {
    expect(alanAdlari([])).toEqual([]);
    expect(alanAdlari(["Data"])).toEqual(["otomasyon_araci", "sistemler", "mesaj_semasi", "donusum_kurallari", "teslim_garantisi"]);
  });

  it("Web: tarayıcı ve çözünürlük; Mobil: OS matrisi, cihaz, uygulama tipi; Desktop: teknoloji…", () => {
    expect(alanAdlari(["Web"])).toEqual(["otomasyon_araci", "tarayicilar", "cozunurlukler"]);
    expect(alanAdlari(["Mobil-Android"])).toEqual(["otomasyon_araci", "os_matrisi", "cihazlar", "uygulama_tipi"]);
    expect(alanAdlari(["Desktop-macOS"])).toEqual(["otomasyon_araci", "os_matrisi", "teknoloji", "mimari", "dagitim", "yol_limiti", "soak_suresi"]);
  });

  it("API sözleşmesi metni yalnız 'API sözleşmesi var' işaretliyse (ya da eski kayıtta metin doluysa)", () => {
    expect(alanAdlari(["API"])).toEqual(["otomasyon_araci", "api_sozlesmesi_var", "auth_tipi"]);
    expect(alanAdlari(["API"], { api_sozlesmesi_var: true })).toContain("api_sozlesmesi");
    expect(alanAdlari(["API"], { api_sozlesmesi_var: false, api_sozlesmesi: "openapi: 3" })).not.toContain("api_sozlesmesi");
    expect(alanGorunur("api_sozlesmesi", EK_BILGI_ALANLARI.api_sozlesmesi, { platformlar: ["API"], ek_bilgi: { api_sozlesmesi: "openapi: 3" } })).toBe(true);
  });

  it("platform seçimi katalog sırasını korur", () => {
    let s = varsayilanSecenekler();
    s = platformDegistir(s, "API", true);
    s = platformDegistir(s, "Web", true);
    expect(s.platformlar).toEqual(["Web", "API"]);
    expect(platformDegistir(s, "Web", false).platformlar).toEqual(["API"]);
  });
});

describe("standart etiketleri", () => {
  it("virgülle birden çok kod; kırpılır, tekrar (büyük/küçük harf) eklenmez", () => {
    const r = standartEkle(["WCAG 2.2 AA"], " OWASP MASVS L1 ,  wcag 2.2 aa,ISO 25010 ");
    expect(r).toEqual({ liste: ["WCAG 2.2 AA", "OWASP MASVS L1", "ISO 25010"], hata: null });
    expect(standartSil(r.liste, "ISO 25010")).toEqual(["WCAG 2.2 AA", "OWASP MASVS L1"]);
    expect(standartEkle(["A"], " , ")).toEqual({ liste: ["A"], hata: null });
  });

  it("40 karakteri aşan kod ve 10'dan fazla kod reddedilir; liste değişmez", () => {
    expect(standartEkle([], "x".repeat(41)).hata).toMatch(/en fazla 40 karakter/);
    const on = Array.from({ length: 10 }, (_, i) => `S${i}`);
    expect(standartEkle(on, "S10")).toEqual({ liste: on, hata: "En fazla 10 standart eklenebilir." });
  });
});

describe("gövde ve doğrulama", () => {
  it("gövde: metinler kırpılır; ek bilgiden yalnız görünen ve dolu alanlar; 'hayır' gönderilmez", () => {
    const s = {
      ...varsayilanSecenekler(),
      platformlar: ["Web"],
      benimsenen_standartlar: [" WCAG 2.2 AA "],
      kapsam_disi: "  ödeme  ",
      roller: " bayi ",
      ek_bilgi: { tarayicilar: " Chrome, Firefox ", cozunurlukler: "  ", cihazlar: "Pixel 8", api_sozlesmesi_var: false },
    };
    expect(uretimGovdesi(s)).toEqual({
      platformlar: ["Web"],
      test_seviyesi: "SYSTEM",
      benimsenen_standartlar: ["WCAG 2.2 AA"],
      kapsam_disi: "ödeme",
      roller: "bayi",
      ek_bilgi: { tarayicilar: "Chrome, Firefox" },
    });
    const api = uretimGovdesi({ ...varsayilanSecenekler(), platformlar: ["API"], ek_bilgi: { api_sozlesmesi_var: true, api_sozlesmesi: "openapi: 3.1\n" } });
    expect(api.ek_bilgi).toEqual({ api_sozlesmesi_var: true, api_sozlesmesi: "openapi: 3.1" });
  });

  it("sınırlar ve bilinmeyen değerler (core 422 karşılığı)", () => {
    expect(secenekHatalari(uretimGovdesi(varsayilanSecenekler()))).toEqual([]);
    const h = secenekHatalari({
      platformlar: ["Web", "Tablet"],
      test_seviyesi: "SMOKE",
      benimsenen_standartlar: [""],
      kapsam_disi: "x".repeat(2001),
      roller: "r".repeat(1001),
      ek_bilgi: { tarayicilar: "t".repeat(501), mimari: "x86", api_sozlesmesi_var: "evet", api_sozlesmesi: "a".repeat(8000), bilinmeyen: "1" },
    });
    expect(h).toEqual([
      "Bilinmeyen platform: Tablet",
      "Bilinmeyen test seviyesi: SMOKE",
      'Standart kodu 1–40 karakter olmalı: ""',
      "Kapsam dışı en fazla 2000 karakter olabilir.",
      "Roller en fazla 1000 karakter olabilir.",
      "Tarayıcılar en fazla 500 karakter olabilir.",
      "Mimari: geçersiz seçim (x86).",
      "API sözleşmesi var: evet/hayır olmalı.",
      "Bilinmeyen ek bilgi alanı: bilinmeyen",
    ]);
    expect(secenekHatalari({ ek_bilgi: { api_sozlesmesi: "a".repeat(8001) } })).toEqual(["API sözleşmesi (OpenAPI/endpoint tanımı) en fazla 8000 karakter olabilir."]);
  });

  it("seçenek gövdesi mi: yalnız kip taşıyan gövde seçenek sayılmaz", () => {
    expect(secenekGovdesiMi(undefined)).toBe(false);
    expect(secenekGovdesiMi({ kip: "tek" })).toBe(false);
    expect(secenekGovdesiMi({ platformlar: [] })).toBe(true);
  });
});

describe("replay adları", () => {
  it("platform eki: tekil, sıralı, '-' ile; platform yoksa null", () => {
    expect(platformReplayAdi(["Web"], "TPD-4")).toBe("platform-web/TPD-4");
    expect(platformReplayAdi(["Web", "API"], "TPD-4")).toBe("platform-api-web/TPD-4");
    expect(platformReplayAdi(["Mobil-iOS", "Mobil-Android", "Desktop-Win", "Data"], "K")).toBe("platform-data-desktop-mobile/K");
    expect(platformReplayAdi([], "TPD-4")).toBeNull();
  });

  it("derinleştirme: negatif/<kök>, teknik-<teknik>/<kök>", () => {
    expect(derinlestirmeReplayAdi("negatif", null, "TPD-1")).toBe("negatif/TPD-1");
    expect(derinlestirmeReplayAdi("teknik", "BVA", "TPD-4")).toBe("teknik-bva/TPD-4");
  });
});

describe("derinleştirme kuralları", () => {
  it("durum uyarlaması: bilinmeyen durum 'yok', eksik listeler boş", () => {
    expect(derinlestirmeDurumuUyarla({ durum: "x" })).toMatchObject({ durum: "yok", uyarilar: [], hata: null });
    expect(derinlestirmeDurumuUyarla({ durum: "tamam", tur: "teknik", teknik: "BVA", uretim_no: 3, yeni_case_sayisi: 2, uyarilar: ["u", 1] })).toEqual({
      durum: "tamam",
      tur: "teknik",
      teknik: "BVA",
      uretim_no: 3,
      yeni_case_sayisi: 2,
      uyarilar: ["u"],
      hata: null,
    });
  });

  it("engel: yalnız cases_ready ve çalışan derinleştirme yokken etkin", () => {
    expect(derinlestirmeEngeli("cases_ready", { durum: "tamam" })).toBeNull();
    expect(derinlestirmeEngeli("cases_ready", null)).toBeNull();
    expect(derinlestirmeEngeli("generating", null)).toMatch(/yalnız case'leri hazır gereksinimde/);
    expect(derinlestirmeEngeli("cases_ready", { durum: "calisiyor" })).toMatch(/sürüyor/);
  });

  it("sonuç metni", () => {
    const d = derinlestirmeDurumuUyarla({ durum: "tamam", yeni_case_sayisi: 3, uretim_no: 2 });
    expect(derinlestirmeSonucu(d)).toBe("3 yeni taslak eklendi (üretim 2).");
    expect(derinlestirmeSonucu({ ...d, yeni_case_sayisi: 0 })).toBe("Yeni taslak eklenmedi.");
    expect(derinlestirmeSonucu({ ...d, durum: "hata" })).toBeNull();
  });
});
