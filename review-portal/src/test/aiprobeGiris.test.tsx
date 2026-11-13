// AI Probe ortak girişi — portal (specs/010-aiprobe-sso T040–T043): kip core'un `X-TP-Kimlik`
// başlığından; local kipte arayüz değişmez.
import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import {
  cikisYonlendirmesi,
  gezinti,
  guvenliDevam,
  kimlikBasligiAyristir,
  kimlikKipi,
  kimlikKipiniAyarla,
  useKimlikServisiErisilemez,
  yanitBasliklariniOku,
} from "../lib/kimlikKipi";
import { AIPROBE_KIPI, BOTH_KIPI, cagrildi, sahteSunucu } from "./sahteSunucu";

const ANALIST = { id: "u-analist", kullanici_adi: "ayse-analyst", rol: "analyst", gorunen_ad: "Ayşe · Analist", ad_soyad: "Ayşe", kisiler: {} };
const AIPROBE_ME = { ...ANALIST, product: "testing-probe", roles: ["analyst", "po"], products: { tp: ["analyst", "po"], ap: ["user"] } };
const YETKISIZ = { status: 401, govde: { detail: "Oturum açmanız gerekiyor" } };

function Konum() {
  const k = useLocation();
  return <output data-testid="konum">{k.pathname + k.search}</output>;
}

function uygulama(yol: string) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          <Rotalar />
          <Konum />
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

describe("kimlik başlığı", () => {
  it("ayrıştırır; tanınmayan/eksik değer local, güvensiz köken atılır", () => {
    expect(kimlikBasligiAyristir("kip=aiprobe; home=https://home.test; urun=testing-probe")).toEqual({
      kip: "aiprobe",
      home: "https://home.test",
      urun: "testing-probe",
    });
    expect(kimlikBasligiAyristir(null).kip).toBe("local");
    expect(kimlikBasligiAyristir("kip=root").kip).toBe("local");
    expect(kimlikBasligiAyristir("kip=both; home=javascript:alert(1)").home).toBeNull();
    expect(kimlikBasligiAyristir("kip=both; home=http://evil.test").home).toBeNull();
  });

  it("continue yalnız göreli yol; çıkış yönlendirmesi yalnız home ya da aynı köken", () => {
    expect(guvenliDevam("/x?y=1")).toBe("/x?y=1");
    for (const k of ["//evil", "https://evil", "/a\\b", "x", "/a:b"]) expect(guvenliDevam(k)).toBe("/");
    kimlikKipiniAyarla({ kip: "aiprobe", home: "https://home.test" });
    expect(cikisYonlendirmesi("https://home.test/logout?product=testing-probe")).toBe("https://home.test/logout?product=testing-probe");
    expect(cikisYonlendirmesi("https://evil.test/logout")).toBeNull();
    expect(cikisYonlendirmesi(42)).toBeNull();
  });
});

describe("local kip (başlık yok): arayüz bugünküyle aynı", () => {
  it("401 → /giris yerel formu; AI Probe düğmesi, değiştirici, yönlendirme yok", async () => {
    sahteSunucu({ "GET /auth/me": YETKISIZ });
    const git = vi.spyOn(gezinti, "git").mockImplementation(() => {});
    uygulama("/kosular");
    expect(await screen.findByLabelText("Kullanıcı adı")).toBeInTheDocument();
    expect(screen.getByTestId("konum")).toHaveTextContent("/giris");
    expect(screen.queryByText("AI Probe hesabıyla giriş yap")).not.toBeInTheDocument();
    expect(git).not.toHaveBeenCalled();
  });

  it("oturumda değiştirici ve uyarı bandı yok; çıkış /giris'e", async () => {
    const f = sahteSunucu({ "GET /auth/me": { govde: ANALIST }, "POST /auth/logout": { govde: { ok: true } } });
    const git = vi.spyOn(gezinti, "git").mockImplementation(() => {});
    uygulama("/denetim");
    await screen.findByRole("button", { name: "Çıkış" });
    expect(screen.queryByTestId("aiprobe-degistirici")).not.toBeInTheDocument();
    expect(screen.queryByTestId("kimlik-servisi-bandi")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Çıkış" }));
    await waitFor(() => expect(screen.getByTestId("konum")).toHaveTextContent("/giris"));
    expect(cagrildi(f, "POST", "/auth/logout")).toHaveLength(1);
    expect(git).not.toHaveBeenCalled();
  });

  it("/rol-sec local kipte ana sayfaya döner (uç çağrılmaz)", async () => {
    const f = sahteSunucu({ "GET /auth/me": YETKISIZ });
    uygulama("/rol-sec");
    await waitFor(() => expect(screen.getByTestId("konum")).not.toHaveTextContent("/rol-sec"));
    expect(cagrildi(f, "GET", "/auth/aiprobe/hesaplar")).toHaveLength(0);
  });
});

describe("aiprobe kip", () => {
  it("oturum yoksa AI Probe girişine continue ile tam sayfa yönlendirir", async () => {
    sahteSunucu({ "GET /auth/me": YETKISIZ }, AIPROBE_KIPI);
    const git = vi.spyOn(gezinti, "git").mockImplementation(() => {});
    uygulama("/gereksinimler/r1?sekme=bulgular");
    await waitFor(() => expect(git).toHaveBeenCalledWith("/api/auth/aiprobe/login?continue=%2Fgereksinimler%2Fr1%3Fsekme%3Dbulgular"));
    expect(screen.queryByLabelText("Kullanıcı adı")).not.toBeInTheDocument();
  });

  it("dönüşte oturum yine açılamıyorsa sonsuz döngü yerine 'Tekrar dene'", async () => {
    sessionStorage.setItem("tp-aiprobe-yonlendirme", JSON.stringify([Date.now(), Date.now(), Date.now()]));
    sahteSunucu({ "GET /auth/me": YETKISIZ }, AIPROBE_KIPI);
    const git = vi.spyOn(gezinti, "git").mockImplementation(() => {});
    uygulama("/kosular");
    expect(await screen.findByRole("heading", { name: "Oturum açılamadı" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tekrar dene" })).toHaveAttribute("href", "/api/auth/aiprobe/login?continue=%2Fkosular");
    expect(git).not.toHaveBeenCalled();
  });

  it("/giris: yerel form yok, yalnız AI Probe girişi", async () => {
    sahteSunucu({ "GET /auth/me": YETKISIZ }, AIPROBE_KIPI);
    uygulama("/giris");
    expect(await screen.findByRole("link", { name: "AI Probe hesabıyla giriş yap" })).toHaveAttribute("href", "/api/auth/aiprobe/login?continue=%2F");
    expect(screen.queryByLabelText("Kullanıcı adı")).not.toBeInTheDocument();
  });

  it("oturum ortasında 401: form verisi yedeklenir, AI Probe girişine gidilir", async () => {
    let me = 0;
    sahteSunucu(
      {
        "GET /auth/me": () => (me++ === 0 ? { govde: AIPROBE_ME } : YETKISIZ),
        "GET /audit": YETKISIZ,
      },
      AIPROBE_KIPI,
    );
    const git = vi.spyOn(gezinti, "git").mockImplementation(() => {});
    uygulama("/denetim");
    await waitFor(() => expect(git).toHaveBeenCalledWith("/api/auth/aiprobe/login?continue=%2Fdenetim"));
  });

  it("uyarı durumu: başlıklı kullanıcı yanıtı açar, başlıksız kapatır; /auth/* (me hariç) dokunmaz", () => {
    const y = (b: Record<string, string>, ok = true) => ({ ok, headers: new Headers(b) });
    const { result } = renderHook(() => useKimlikServisiErisilemez());
    act(() => yanitBasliklariniOku(y({ ...AIPROBE_KIPI, "X-Aiprobe-Degraded": "1" }), "/requirements"));
    expect(kimlikKipi().kip).toBe("aiprobe");
    expect(result.current).toBe(true);
    act(() => yanitBasliklariniOku(y(AIPROBE_KIPI), "/auth/logout"));
    expect(result.current).toBe(true);
    act(() => yanitBasliklariniOku(y(AIPROBE_KIPI), "/requirements?x=1"));
    expect(result.current).toBe(false);
    // Core local'e dönerse (başlık yok) kip de döner.
    act(() => yanitBasliklariniOku(y({}, false), "/auth/me"));
    expect(kimlikKipi().kip).toBe("local");
  });

  it("X-Aiprobe-Degraded: uyarı bandı (role=status)", async () => {
    sahteSunucu({ "GET /auth/me": { govde: AIPROBE_ME, basliklar: { "X-Aiprobe-Degraded": "1" } } }, AIPROBE_KIPI);
    uygulama("/denetim");
    const band = await screen.findByTestId("kimlik-servisi-bandi");
    expect(band).toHaveTextContent("AI Probe kimlik servisine şu anda ulaşılamıyor");
    expect(band).toHaveAttribute("role", "status");
  });

  it("AI Probe kaynaklı ad üst çubukta '(AI Probe)' ile işaretlenir", async () => {
    sahteSunucu({ "GET /auth/me": { govde: { ...AIPROBE_ME, ad_kaynak: "aiprobe" } } }, AIPROBE_KIPI);
    uygulama("/denetim");
    const isaret = await screen.findByTestId("ad-kaynak");
    expect(isaret).toHaveTextContent("(AI Probe)");
    expect(isaret.closest(".kullanici-ad")).toHaveTextContent("Ayşe (AI Probe)");
  });

  it("yerel kaynaklı adda işaret yok", async () => {
    sahteSunucu({ "GET /auth/me": { govde: AIPROBE_ME } }, AIPROBE_KIPI);
    uygulama("/denetim");
    expect(await screen.findByText("Ayşe")).toBeInTheDocument();
    expect(screen.queryByTestId("ad-kaynak")).not.toBeInTheDocument();
  });

  it("çıkış yanıttaki AI Probe çıkış sayfasına gider; yabancı köken yok sayılır", async () => {
    const f = sahteSunucu(
      {
        "GET /auth/me": { govde: AIPROBE_ME },
        "POST /auth/logout": { govde: { ok: true, redirect: "https://home.test/logout?product=testing-probe" } },
      },
      AIPROBE_KIPI,
    );
    const git = vi.spyOn(gezinti, "git").mockImplementation(() => {});
    uygulama("/denetim");
    await userEvent.click(await screen.findByRole("button", { name: "Çıkış" }));
    await waitFor(() => expect(git).toHaveBeenCalledWith("https://home.test/logout?product=testing-probe"));
    expect(cagrildi(f, "POST", "/auth/logout")).toHaveLength(1);
  });

  it("çıkış yanıtında yönlendirme yoksa (ya da yabancıysa) AI Probe ana sayfası", async () => {
    sahteSunucu(
      { "GET /auth/me": { govde: AIPROBE_ME }, "POST /auth/logout": { govde: { ok: true, redirect: "https://evil.test/x" } } },
      AIPROBE_KIPI,
    );
    const git = vi.spyOn(gezinti, "git").mockImplementation(() => {});
    uygulama("/denetim");
    await userEvent.click(await screen.findByRole("button", { name: "Çıkış" }));
    await waitFor(() => expect(git).toHaveBeenCalledWith("https://home.test/"));
  });
});

describe("both kip", () => {
  it("/giris yerel formu ve AI Probe düğmesini birlikte gösterir; 401 yönlendirmez", async () => {
    sahteSunucu({ "GET /auth/me": YETKISIZ }, BOTH_KIPI);
    const git = vi.spyOn(gezinti, "git").mockImplementation(() => {});
    uygulama("/kosular");
    expect(await screen.findByLabelText("Kullanıcı adı")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AI Probe hesabıyla giriş yap" })).toHaveAttribute("href", "/api/auth/aiprobe/login?continue=%2Fkosular");
    expect(git).not.toHaveBeenCalled();
  });
});

describe("/rol-sec", () => {
  const HESAPLAR = [
    { id: "h-analist", kullanici_adi: "ayse-analyst", rol: "analyst", gorunen_ad: "Ayşe · Analist" },
    { id: "h-po", kullanici_adi: "ayse-po", rol: "po", gorunen_ad: "Ayşe · PO" },
  ];

  it("girişte: hesaplar listelenir, seçim oturumu açar ve continue'ya döner", async () => {
    let oturum = false;
    const f = sahteSunucu(
      {
        "GET /auth/me": () => (oturum ? { govde: { ...AIPROBE_ME, rol: "po" } } : YETKISIZ),
        "GET /auth/aiprobe/hesaplar": { govde: { hesaplar: HESAPLAR, continue: "/denetim" } },
        "POST /auth/aiprobe/rol-sec": () => {
          oturum = true;
          return { govde: { ...AIPROBE_ME, id: "h-po", rol: "po", continue: "/denetim" } };
        },
      },
      AIPROBE_KIPI,
    );
    vi.spyOn(gezinti, "git").mockImplementation(() => {});
    uygulama("/rol-sec?continue=%2Fdenetim");
    expect(await screen.findByRole("heading", { name: "Rol seçin" })).toBeInTheDocument();
    const liste = screen.getByRole("list", { name: "Rol hesapları" });
    expect(within(liste).getAllByRole("button")).toHaveLength(2);
    await userEvent.click(within(liste).getByRole("button", { name: /PO/ }));
    await waitFor(() => expect(screen.getByTestId("konum")).toHaveTextContent("/denetim"));
    const [istek] = cagrildi(f, "POST", "/auth/aiprobe/rol-sec");
    expect(JSON.parse(String(istek!.body))).toEqual({ app_user_id: "h-po" });
  });

  it("seçim süresi dolduysa (401) yeniden giriş bağlantısı", async () => {
    sahteSunucu({ "GET /auth/me": YETKISIZ, "GET /auth/aiprobe/hesaplar": YETKISIZ }, AIPROBE_KIPI);
    uygulama("/rol-sec?continue=%2Fkosular");
    expect(await screen.findByText("Rol seçiminin süresi doldu; yeniden giriş yapın.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Yeniden giriş yap" })).toHaveAttribute("href", "/api/auth/aiprobe/login?continue=%2Fkosular");
  });

  it("açık oturumda 'Rol değiştir': aktif hesap işaretli, rol-degistir çağrılır", async () => {
    const f = sahteSunucu(
      {
        "GET /auth/me": { govde: AIPROBE_ME },
        "GET /auth/aiprobe/hesaplar": { govde: { hesaplar: HESAPLAR, aktif_id: "u-analist" } },
        "POST /auth/aiprobe/rol-degistir": { govde: { ...AIPROBE_ME, id: "h-po", rol: "po" } },
      },
      AIPROBE_KIPI,
    );
    uygulama("/rol-sec?continue=%2Fdenetim");
    expect(await screen.findByRole("heading", { name: "Rol değiştir" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /PO/ }));
    await waitFor(() => expect(cagrildi(f, "POST", "/auth/aiprobe/rol-degistir")).toHaveLength(1));
    expect(await screen.findByText("Rol değiştirildi: PO.")).toBeInTheDocument();
  });

  it("403 (bağlı olmayan hesap) Türkçe hata olarak gösterilir, oturum değişmez", async () => {
    sahteSunucu(
      {
        "GET /auth/me": { govde: AIPROBE_ME },
        "GET /auth/aiprobe/hesaplar": { govde: { hesaplar: HESAPLAR, aktif_id: "u-analist" } },
        "POST /auth/aiprobe/rol-degistir": { status: 403, govde: { detail: "Bu rol AI Probe hesabınızda tanımlı değil", kod: "yasak" } },
      },
      AIPROBE_KIPI,
    );
    uygulama("/rol-sec");
    await userEvent.click(await screen.findByRole("button", { name: /PO/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Bu rol AI Probe hesabınızda tanımlı değil");
    expect(screen.getByTestId("konum")).toHaveTextContent("/rol-sec");
  });
});
