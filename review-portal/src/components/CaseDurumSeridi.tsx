import { useCallback, type MouseEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import type { AcikSoruKaydi } from "../api/acikSoruTipleri";
import type { CaseDenetimGorunumu, TestCase } from "../api/types";
import { acikSoruSayimi, caseHazirlik, type AcikSoruSayimi } from "../lib/caseV3";
import { DENETIM_KARARI } from "./KalitePanelleri";

/** Case review sayfasındaki bölüm kimlikleri (durum şeridi ve "göster" bağlantılarının hedefi). */
export const CASE_KARARLARI_ID = "case-kararlari";
export const DENETIM_ID = "denetim";
/** Açık sorular ve PO yanıtları paneli (AcikSorularPaneli `Kart id`). */
export const ACIK_SORULAR_ID = "acik-sorular";

/**
 * B8: durum şeridinin açık soru öğesi. Sıradaki eylemi öne alır: PO yanıtı geldiyse (düzelt), soru
 * gönderilmediyse (gönder), yalnız yanıt bekleniyorsa (bekle). Soru yoksa ya da core alanı yoksa null.
 */
export function acikSoruSeritDurumu(s: AcikSoruSayimi | null): { metin: string; ton: SeritTonu } | null {
  if (!s) return null;
  const parcalar: string[] = [];
  if (s.yanitlandi) parcalar.push(`${s.yanitlandi} PO yanıtı geldi`);
  if (s.gonderilmedi) parcalar.push(`${s.gonderilmedi} soru PO'ya gönderilmedi`);
  if (s.gonderildi) parcalar.push(`${s.gonderildi} PO yanıtı bekleniyor`);
  if (!parcalar.length) return null;
  return { metin: parcalar.join(" · "), ton: s.yanitlandi || s.gonderilmedi ? "uyari" : "notr" };
}

/**
 * Sayfa içi bölüme kaydırır ve odağı taşır (klavye/ekran okuyucu kullanıcısı bölümde kalır).
 * Hedef odaklanabilir değilse `tabindex="-1"` eklenir. Bölüm yoksa hiçbir şey yapmaz.
 */
export function bolumeGit(id: string): boolean {
  const el = document.getElementById(id);
  if (!el) return false;
  el.scrollIntoView?.({ block: "start" });
  if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
  el.focus({ preventScroll: true });
  return true;
}

/** Yeni görünüm çizildikten sonra bölüme git (arama parametresi değişince liste yeniden süzülür). */
function sonraBolumeGit(id: string) {
  const calis = () => bolumeGit(id);
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(() => requestAnimationFrame(calis));
  else setTimeout(calis, 0);
}

/**
 * Case listesine (A2 bölgesi, `#case-kararlari`) arama parametresiyle git: `filtre=hazir-degil`,
 * `uretim=<no>` … Diğer parametreler korunur; liste A2'nin süzgecinde bu parametrelerle süzülür.
 */
export function useCaseListesineGit() {
  const navigate = useNavigate();
  const location = useLocation();
  return useCallback(
    (parametreler: Record<string, string> = {}) => {
      const p = new URLSearchParams(location.search);
      for (const [k, v] of Object.entries(parametreler)) p.set(k, v);
      const search = p.toString();
      navigate({ pathname: location.pathname, search: search ? `?${search}` : "", hash: CASE_KARARLARI_ID });
      sonraBolumeGit(CASE_KARARLARI_ID);
    },
    [navigate, location.pathname, location.search],
  );
}

/** Onay için hazır olmayan güncel case: hazır olma durumu "ready" değil ya da core onay engeli var. */
export function hazirDegilMi(c: TestCase): boolean {
  if (c.durum === "rejected" || c.durum === "superseded") return false;
  return caseHazirlik(c) !== "ready" || !!c.onay_engeli;
}

export type SeritTonu = "notr" | "uyari" | "basari" | "hata";

/** Durum şeridinin "Agent Probe denetimi: …" öğesi (görünüm yoksa — eski core — null). */
export function denetimSeritDurumu(g: CaseDenetimGorunumu | null | undefined): { metin: string; ton: SeritTonu } | null {
  if (!g) return null;
  if (!g.kapi_acik) return { metin: "kapı kapalı", ton: "notr" };
  if (g.calisiyor) return { metin: "sürüyor", ton: "notr" };
  const k = g.guncel_karar;
  if (k?.karar) return { metin: DENETIM_KARARI[k.karar]?.etiket ?? k.karar, ton: k.karar === "KABUL" ? "basari" : k.karar === "ENGELLE" ? "hata" : "uyari" };
  const son = g.denetim;
  if (son && son.durum === "hata" && son.guncel !== false) return { metin: "yapılamadı", ton: "hata" };
  if (son && son.guncel === false) return { metin: "karar bayat", ton: "uyari" };
  return { metin: "karar yok", ton: "uyari" };
}

/** Yayın kapısı açık mı: denetim görünümü yoksa (eski core) ya da kapı kapalıysa ya da engel yoksa. */
export function yayinAcikMi(g: CaseDenetimGorunumu | null | undefined): boolean {
  if (!g) return true;
  return !g.kapi_acik || !g.yayin_engeli;
}

function BolumBaglantisi({ hedef, children, testId }: { hedef: string; children: ReactNode; testId: string }) {
  const location = useLocation();
  const git = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    sonraBolumeGit(hedef);
  };
  return (
    <Link to={{ pathname: location.pathname, search: location.search, hash: hedef }} onClick={git} data-testid={testId}>
      {children}
    </Link>
  );
}

/**
 * Case review sayfa başı durum şeridi (UX-3): karar bekleyen ve hazır olmayan case sayısı, Agent
 * Probe denetimi ve yayın durumu; her öğe ilgili bölüme bağlantıdır. Renk tek başına anlam taşımaz:
 * her öğenin durumu metindedir.
 */
export function CaseDurumSeridi({
  caseler,
  denetim,
  yayinYolu,
  acikSorular,
}: {
  caseler: TestCase[];
  denetim: CaseDenetimGorunumu | null | undefined;
  yayinYolu: string;
  /** Core açık soru listesi (panelden): hiçbir case'e bağlı olmayan soru da sayılır (UX4 Bulgu 2). */
  acikSorular?: readonly AcikSoruKaydi[] | null;
}) {
  const location = useLocation();
  const listeyeGit = useCaseListesineGit();
  const bekleyen = caseler.filter((c) => c.durum === "draft").length;
  const hazirDegil = caseler.filter(hazirDegilMi).length;
  const dn = denetimSeritDurumu(denetim);
  const acik = acikSoruSeritDurumu(acikSoruSayimi(caseler, acikSorular));
  const yayinAcik = yayinAcikMi(denetim);
  const hazirDegilParam = new URLSearchParams(location.search);
  hazirDegilParam.set("filtre", "hazir-degil");
  return (
    <nav aria-label="Case review durumu" className="durum-seridi" data-testid="durum-seridi">
      <ul>
        <li className={bekleyen > 0 ? "durum-seridi-uyari" : "durum-seridi-basari"}>
          <BolumBaglantisi hedef={CASE_KARARLARI_ID} testId="serit-bekleyen">
            {bekleyen > 0 ? `${bekleyen} karar bekliyor` : "Karar bekleyen yok"}
          </BolumBaglantisi>
        </li>
        <li className={hazirDegil > 0 ? "durum-seridi-uyari" : "durum-seridi-notr"}>
          <Link
            to={{ pathname: location.pathname, search: `?${hazirDegilParam.toString()}`, hash: CASE_KARARLARI_ID }}
            onClick={(e) => {
              if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
              e.preventDefault();
              listeyeGit({ filtre: "hazir-degil" });
            }}
            data-testid="serit-hazir-degil"
          >
            {hazirDegil} hazır değil
          </Link>
        </li>
        {acik && (
          <li className={`durum-seridi-${acik.ton}`}>
            <BolumBaglantisi hedef={ACIK_SORULAR_ID} testId="serit-acik-sorular">
              {acik.metin}
            </BolumBaglantisi>
          </li>
        )}
        {dn && (
          <li className={`durum-seridi-${dn.ton}`}>
            <BolumBaglantisi hedef={DENETIM_ID} testId="serit-denetim">
              Agent Probe denetimi: {dn.metin}
            </BolumBaglantisi>
          </li>
        )}
        <li className={yayinAcik ? "durum-seridi-basari" : "durum-seridi-notr"}>
          <Link to={yayinYolu} data-testid="serit-yayin">
            Yayın: {yayinAcik ? "açık" : "kapalı"}
          </Link>
        </li>
      </ul>
    </nav>
  );
}
