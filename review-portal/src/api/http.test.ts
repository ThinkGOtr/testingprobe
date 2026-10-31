import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { ApiError, BU_FAZDA_YOK, buFazdaYok, canliDerleme, UC_YOK, cakismaMesaji, ICERIK_DEGISTI, kararCakismasi, istek, mockOturumuAyarla, mockUclari, ucuNormallestir, ucVar, yapilandir, yetenekleriAyristir, yetkisizOlunca } from "./http";

function yanit(status: number, govde: unknown, json = true): Response {
  return new Response(json ? JSON.stringify(govde) : String(govde), {
    status,
    headers: { "Content-Type": json ? "application/json" : "text/html" },
  });
}

describe("istek (gerçek mod)", () => {
  afterEach(() => {
    yetkisizOlunca(null);
    vi.unstubAllGlobals();
  });

  it("/api önekiyle, çerezle ve JSON gövdeyle gönderir", async () => {
    yapilandir({ mockZorunlu: false });
    const f = vi.fn().mockImplementation(() => Promise.resolve(yanit(200, { id: "u1", kullanici_adi: "analist", rol: "analyst" })));
    vi.stubGlobal("fetch", f);
    const k = await api.login("analist", "x");
    expect(k.rol).toBe("analyst");
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/auth/login");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    expect(JSON.parse(String(init.body))).toEqual({ kullanici_adi: "analist", parola: "x" });
  });

  it("sorgu parametrelerini kodlar, boş değerleri atar", async () => {
    yapilandir({ mockZorunlu: false });
    const f = vi.fn().mockImplementation(() => Promise.resolve(yanit(200, [])));
    vi.stubGlobal("fetch", f);
    await api.caseler("req 1");
    await api.caseler();
    expect(f.mock.calls[0][0]).toBe("/api/cases?requirement_id=req+1");
    expect(f.mock.calls[1][0]).toBe("/api/cases");
  });

  it("hata gövdesindeki detail'i ApiError olarak verir", async () => {
    yapilandir({ mockZorunlu: false });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(409, { detail: "PO teyidi olmadan case üretilemez." }))));
    await expect(api.caseUret("r1")).rejects.toMatchObject({ status: 409, detail: "PO teyidi olmadan case üretilemez." });
  });

  it("FastAPI doğrulama hatalarını (422 dizi) birleştirir", async () => {
    yapilandir({ mockZorunlu: false });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(422, { detail: [{ msg: "alan zorunlu" }, { msg: "çok uzun" }] }))));
    await expect(api.serbestMetin({ baslik: "", aciklama: "", ac: [] })).rejects.toMatchObject({ detail: "alan zorunlu; çok uzun" });
  });

  it("genel 404'te (uç yok) mock'a düşer ve ucu kaydeder", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: true });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(404, { detail: "Not Found" }))));
    // OturumProvider gerçek girişte mock tarafına da oturumu bildirir; burada elle.
    mockOturumuAyarla(await api.login("analist", "Demo123!"));
    const liste = await api.gereksinimler();
    expect(liste.map((g) => g.jira_key)).toContain("TPD-1");
    expect(mockUclari()).toEqual(["GET /requirements", "POST /auth/login"]);
  });

  it("JSON olmayan 404'te (nginx) de mock'a düşer", async () => {
    yapilandir({ mockZorunlu: false });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(404, "<html>404</html>", false))));
    await expect(api.login("muhendis", "x")).resolves.toMatchObject({ rol: "engineer" });
  });

  it("kayıt bulunamadı 404'ünde mock'a düşmez", async () => {
    yapilandir({ mockZorunlu: false });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(404, { detail: "Gereksinim bulunamadı: x" }))));
    await expect(api.gereksinim("x")).rejects.toMatchObject({ status: 404, detail: "Gereksinim bulunamadı: x" });
    expect(mockUclari()).toEqual([]);
  });

  it("otomatik mock kapalıysa genel 404 hata olur", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(404, { detail: "Not Found" }))));
    await expect(api.kosular()).rejects.toBeInstanceOf(ApiError);
  });

  it("401'de yetkisiz dinleyicisini çağırır (auth uçları hariç)", async () => {
    yapilandir({ mockZorunlu: false });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(401, { detail: "Oturum gerekli" }))));
    const dinleyici = vi.fn();
    yetkisizOlunca(dinleyici);
    await expect(api.kosular()).rejects.toMatchObject({ status: 401 });
    expect(dinleyici).toHaveBeenCalledTimes(1);
    await expect(api.me()).rejects.toMatchObject({ status: 401 });
    expect(dinleyici).toHaveBeenCalledTimes(1);
  });

  it("ağ hatasını Türkçe mesajla verir; 502'de varsayılan mesaj", async () => {
    yapilandir({ mockZorunlu: false });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api.kosular()).rejects.toMatchObject({ status: 0 });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(502, "Bad gateway", false))));
    await expect(api.kosular()).rejects.toMatchObject({ detail: "Çekirdek servise ulaşılamıyor." });
  });

  it("204 ve boş gövdeyi undefined döndürür", async () => {
    yapilandir({ mockZorunlu: false });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(istek("POST", "/auth/logout")).resolves.toBeUndefined();
  });
});

describe("istemci ↔ sözleşme", () => {
  it("§5'teki her uca doğru yöntem ve yolla gider", async () => {
    yapilandir({ mockZorunlu: false });
    const f = vi.fn().mockImplementation(() => Promise.resolve(yanit(200, {})));
    vi.stubGlobal("fetch", f);
    const cagrilar: [() => Promise<unknown>, string, string][] = [
      [() => api.logout(), "POST", "/api/auth/logout"],
      [() => api.me(), "GET", "/api/auth/me"],
      [() => api.jiradanCek(), "POST", "/api/requirements/sync"],
      [() => api.serbestMetin({ baslik: "b", aciklama: "a", ac: [] }), "POST", "/api/requirements/free-text"],
      [() => api.gereksinim("r/1"), "GET", "/api/requirements/r%2F1"],
      [() => api.incelemeBaslat("r1"), "POST", "/api/requirements/r1/review"],
      [() => api.bulgular("r1"), "GET", "/api/requirements/r1/findings"],
      [() => api.bulguKarari("f1", { icerik_hash: "sha256:h", karar: "fix_doc" }), "POST", "/api/findings/f1/decision"],
      [() => api.duzeltmeleriUygula("r1"), "POST", "/api/requirements/r1/apply-doc-fixes"],
      [() => api.poOnayla({ id: "r1", icerik_hash: "sha256:h" }), "POST", "/api/requirements/r1/po-approve"],
      [() => api.caseUret("r1"), "POST", "/api/requirements/r1/generate-cases"],
      [() => api.caseKarari("c1", { icerik_hash: "sha256:h", karar: "approve" }), "POST", "/api/cases/c1/decision"],
      [() => api.yayinOnizleme("r1"), "GET", "/api/publish/preview?requirement_id=r1"],
      [() => api.yayinla(["c1"]), "POST", "/api/publish"],
      [() => api.kodUret(["c1"]), "POST", "/api/code/generate"],
      [() => api.scriptler(), "GET", "/api/scripts"],
      [() => api.script("s1"), "GET", "/api/scripts/s1"],
      [() => api.kirarakDogrula("s1"), "POST", "/api/scripts/s1/break-verify"],
      [() => api.prBirlestir({ number: 12, icerik_hash: "sha256:h", head_sha: "a".repeat(40) }), "POST", "/api/prs/12/merge"],
      [() => api.ciTetikle("deploy"), "POST", "/api/ci/trigger"],
      [() => api.kosular(), "GET", "/api/runs"],
      [() => api.kosu("run-1"), "GET", "/api/runs/run-1"],
      [() => api.hata("f1"), "GET", "/api/failures/f1"],
      [() => api.onarimPrAc("f1"), "POST", "/api/failures/f1/fix"],
      [() => api.bugTaslaklari(), "GET", "/api/bug-drafts"],
      [() => api.bugTaslagi("b1"), "GET", "/api/bug-drafts/b1"],
      [() => api.bugKarari("b1", { icerik_hash: "sha256:h", karar: "link", link_key: "TPD-21" }), "POST", "/api/bug-drafts/b1/decision"],
      [() => api.kontrolKulesi(), "GET", "/api/control-tower"],
      [() => api.denetim(), "GET", "/api/audit?verify=true"],
      [() => api.tokenOlustur("submit"), "POST", "/api/tokens"],
      [() => api.tokenlar(), "GET", "/api/tokens"],
      [() => api.tokenIptal("t1"), "DELETE", "/api/tokens/t1"],
      [() => api.caseYenidenAc({ id: "c1", icerik_hash: "sha256:h" }), "POST", "/api/cases/c1/decision"],
      [() => api.caseGoruntulendi("c1"), "POST", "/api/cases/c1/viewed"],
      [() => api.caseMetrikleri("r1"), "GET", "/api/requirements/r1/case-metrics"],
      [() => api.demoKir(), "POST", "/api/demo/break-locator"],
      [() => api.demoSifirla(), "POST", "/api/demo/reset"],
    ];
    for (const [fn, yontem, url] of cagrilar) {
      f.mockClear();
      // Yalnızca istek yöntemi ve yolu sınanır; gövde uyarlayıcıları (ör. denetim) {} ile hata verebilir.
      await fn().catch(() => undefined);
      expect([f.mock.calls[0][0], (f.mock.calls[0][1] as RequestInit).method]).toEqual([url, yontem]);
    }
    vi.unstubAllGlobals();
  });

  it("insan kararı uçları görülen içeriğin icerik_hash'ini (merge'de head_sha'yı da) gövdede gönderir", async () => {
    yapilandir({ mockZorunlu: false });
    const f = vi.fn().mockImplementation(() => Promise.resolve(yanit(200, {})));
    vi.stubGlobal("fetch", f);
    const govde = () => JSON.parse(String((f.mock.calls.at(-1)![1] as RequestInit).body)) as Record<string, unknown>;
    const head = "0123456789abcdef0123456789abcdef01234567";

    await api.bulguKarari("f1", { icerik_hash: "sha256:b", karar: "accept_difference", gerekce: "g" });
    expect(govde()).toEqual({ icerik_hash: "sha256:b", karar: "accept_difference", gerekce: "g" });
    await api.caseKarari("c1", { icerik_hash: "sha256:c", karar: "reject", ret_nedeni: "duplicate" });
    expect(govde()).toEqual({ icerik_hash: "sha256:c", karar: "reject", ret_nedeni: "duplicate" });
    await api.bugKarari("b1", { icerik_hash: "sha256:g", karar: "dismiss" });
    expect(govde()).toEqual({ icerik_hash: "sha256:g", karar: "dismiss" });
    // Yeniden açma da görülen içeriğe bağlıdır (TestCase nesnesinin tamamı verilse de yalnızca hash).
    await api.caseYenidenAc({ id: "c1", icerik_hash: "sha256:y" });
    expect(govde()).toEqual({ karar: "reopen", icerik_hash: "sha256:y" });
    // GereksinimDetay / PullRequest nesnesinin tamamı verilse de yalnızca bağ alanları gider.
    await api.poOnayla({ id: "r1", icerik_hash: "sha256:r" });
    expect(govde()).toEqual({ icerik_hash: "sha256:r" });
    await api.prBirlestir({ number: 12, icerik_hash: "sha256:p", head_sha: head });
    expect(govde()).toEqual({ icerik_hash: "sha256:p", head_sha: head });
    expect((f.mock.calls.at(-1)![1] as RequestInit).headers).toMatchObject({ "Content-Type": "application/json" });
    vi.unstubAllGlobals();
  });

  it("409 çakışmasını 'içerik değişti' mesajına çevirir", () => {
    expect(cakismaMesaji(new ApiError(409, "test_case: içerik siz görüntüledikten sonra değişmiş; yenileyip tekrar karar verin"))).toBe(
      ICERIK_DEGISTI,
    );
    expect(cakismaMesaji(new ApiError(409, "PR head sha'sı siz incelediğinizden beri değişmiş"))).toBe(ICERIK_DEGISTI);
    expect(cakismaMesaji(new ApiError(409, "PR açık değil."))).toBe("PR açık değil.");
    // Durum çakışması (içerik değişmedi): "İçerik değişti" öneki yanıltıcı olurdu.
    expect(cakismaMesaji(new ApiError(409, "Gereksinim karar beklemiyor (durum: done)"))).toBe("Gereksinim karar beklemiyor (durum: done)");
    expect(kararCakismasi(new ApiError(409, "x"))).toBe(true);
    expect(kararCakismasi(new ApiError(422, "x"))).toBe(false);
    expect(kararCakismasi(new Error("x"))).toBe(false);
  });

  it("uç adlarını kimliksiz normalleştirir", () => {
    expect(ucuNormallestir("get", "/requirements/req-tpd-1/findings")).toBe("GET /requirements/:id/findings");
    expect(ucuNormallestir("POST", "/requirements/free-text")).toBe("POST /requirements/free-text");
  });
});

describe("core uç keşfi (openapi.json) — örnek veri uçlarına ağ isteği yok", () => {
  const OPENAPI = {
    openapi: "3.1.0",
    paths: {
      "/auth/login": { post: {} },
      "/auth/me": { get: {} },
      "/requirements/{requirement_id}": { parameters: [], get: {} },
      "/events": { get: {} },
    },
  };

  function sahteCore(belge: unknown, openapiDurumu = 200) {
    return vi.fn().mockImplementation((url: string) => {
      if (url === "/api/openapi.json") return Promise.resolve(yanit(openapiDurumu, belge));
      if (url === "/api/auth/login") return Promise.resolve(yanit(200, { id: "u1", kullanici_adi: "analist", rol: "analyst" }));
      if (url.startsWith("/api/requirements/")) return Promise.resolve(yanit(404, { detail: "Gereksinim bulunamadı: x" }));
      return Promise.resolve(yanit(404, { detail: "Not Found" }));
    });
  }

  afterEach(() => vi.unstubAllGlobals());

  it("core'da olmayan uca hiç gitmez, bilinen uca gider; uç listesi bir kez okunur", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: true, yetenekKesfi: true });
    const f = sahteCore(OPENAPI);
    vi.stubGlobal("fetch", f);
    // OturumProvider gerçek girişte mock tarafına da oturumu bildirir; burada elle.
    mockOturumuAyarla(await api.login("analist", "Demo123!"));
    const liste = await api.gereksinimler();
    await api.kosular();
    await api.bugTaslaklari();
    expect(liste.map((g) => g.jira_key)).toContain("TPD-1");
    // {requirement_id} kalıbı: gerçek uca gider, gerçek 404 hata olarak gelir (mock'a düşmez)
    await expect(api.gereksinim("x")).rejects.toMatchObject({ status: 404 });
    const adresler = f.mock.calls.map((c) => c[0] as string);
    expect(adresler).toEqual(["/api/openapi.json", "/api/auth/login", "/api/requirements/x"]);
    expect(mockUclari()).toEqual(["GET /bug-drafts", "GET /requirements", "GET /runs"]);
  });

  it("uç listesi okunamazsa eski davranış: genel 404'te örnek veriye düşer", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: true, yetenekKesfi: true });
    const f = sahteCore({ detail: "Not Found" }, 404);
    vi.stubGlobal("fetch", f);
    mockOturumuAyarla(await api.login("analist", "Demo123!"));
    await api.kosular();
    expect(f.mock.calls.map((c) => c[0])).toEqual(["/api/openapi.json", "/api/auth/login", "/api/runs"]);
    expect(mockUclari()).toEqual(["GET /runs"]);
  });

  it("VITE_MOCK=0 (canlı derleme): core'da olmayan uca gidilmez, örnek veriye de düşülmez — 'bu fazda yok' (501)", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const f = sahteCore(OPENAPI);
    vi.stubGlobal("fetch", f);
    await expect(api.kontrolKulesi()).rejects.toMatchObject({ status: 501, detail: BU_FAZDA_YOK });
    await expect(api.kosular()).rejects.toMatchObject({ status: 501, detail: BU_FAZDA_YOK });
    // Var olan uç core'a gider; gerçek 404 hata olarak kalır.
    await expect(api.gereksinim("x")).rejects.toMatchObject({ status: 404 });
    expect(f.mock.calls.map((c) => c[0])).toEqual(["/api/openapi.json", "/api/requirements/x"]);
    expect(mockUclari()).toEqual([]);
    expect(canliDerleme()).toBe(true);
    expect(buFazdaYok(new ApiError(501, BU_FAZDA_YOK))).toBe(true);
    expect(buFazdaYok(BU_FAZDA_YOK)).toBe(true);
    expect(buFazdaYok(new ApiError(501, UC_YOK))).toBe(false);
  });

  it("VITE_MOCK=0 ve uç listesi okunamazsa: genel 404 de örnek veriye düşmez, 'bu fazda yok' olur", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const f = sahteCore({ detail: "Not Found" }, 404);
    vi.stubGlobal("fetch", f);
    await expect(api.kontrolKulesi()).rejects.toMatchObject({ status: 501, detail: BU_FAZDA_YOK });
    expect(f.mock.calls.map((c) => c[0])).toEqual(["/api/openapi.json", "/api/control-tower"]);
    expect(mockUclari()).toEqual([]);
  });

  it("kaynağı çekirdekte olan işlem, işlem ucu yoksa örnek veriye düşmez (501); kaynak örnek veriyse düşer", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: true, yetenekKesfi: true });
    // core: GET /cases var; görüntüleme ve ölçüm uçları (henüz) yok.
    const belge = { paths: { ...OPENAPI.paths, "/cases": { get: {} } } };
    const f = vi.fn().mockImplementation((url: string) =>
      url === "/api/openapi.json" ? Promise.resolve(yanit(200, belge)) : Promise.resolve(yanit(200, { id: "u1", kullanici_adi: "analist", rol: "analyst" })),
    );
    vi.stubGlobal("fetch", f);
    mockOturumuAyarla(await api.login("analist", "Demo123!"));
    await expect(api.caseYenidenAc({ id: "gercek-case", icerik_hash: "sha256:h" })).rejects.toMatchObject({ status: 501, detail: UC_YOK });
    await expect(api.caseGoruntulendi("gercek-case")).rejects.toMatchObject({ status: 501 });
    await expect(api.caseMetrikleri("gercek-req")).rejects.toMatchObject({ status: 501 });
    expect(mockUclari()).toEqual([]);
    expect(f.mock.calls.map((c) => c[0])).toEqual(["/api/openapi.json", "/api/auth/login"]);
  });

  it("case listesi örnek veriden geliyorsa yeniden açma da örnek veriye gider", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: true, yetenekKesfi: true });
    vi.stubGlobal("fetch", sahteCore(OPENAPI));
    mockOturumuAyarla(await api.login("analist", "Demo123!"));
    const caseler = await api.caseler("req-tpd-1");
    const red = caseler.find((c) => c.durum === "rejected")!;
    const acildi = await api.caseYenidenAc(red);
    // core gibi: durum draft; son karar kaydı (reject) değişmez.
    expect(acildi).toMatchObject({ id: red.id, durum: "draft", karar: "reject" });
    expect(mockUclari()).toEqual(["GET /cases", "POST /cases/:id/decision"]);
  });

  it("uç listesi yokken: kaynak çekirdekten gelmişse genel 404'te de örnek veriye düşülmez", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: true, yetenekKesfi: false });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(404, { detail: "Not Found" }))));
    await expect(api.caseYenidenAc({ id: "c1", icerik_hash: "sha256:h" })).rejects.toMatchObject({ status: 501 });
    expect(mockUclari()).toEqual([]);
  });

  it("OpenAPI ayrıştırma: yol parametresi tek parça, 'parameters' yöntem sayılmaz", () => {
    const y = yetenekleriAyristir(OPENAPI)!;
    expect(ucVar(y, "GET", "/requirements/req-tpd-1")).toBe(true);
    expect(ucVar(y, "GET", "/requirements/req-tpd-1/findings")).toBe(false);
    expect(ucVar(y, "POST", "/requirements/req-tpd-1")).toBe(false);
    expect(ucVar(y, "get", "/events")).toBe(true);
    expect(y.uclar.some((u) => u.method === "PARAMETERS")).toBe(false);
    expect(yetenekleriAyristir({ detail: "x" })).toBeNull();
  });
});
