import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import { CASE_DURUMLARI, type CaseDurumu, type Gereksinim, type TestCase } from "../api/types";
import { BosDurum, Cip, DisBaglanti, HataKutusu, Kart, SayfaBasligi, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useVeri } from "../hooks";
import { CASE_DURUMU, CASE_TURU, RISK } from "../lib/etiketler";
import { guvenliDisAdres, tarih } from "../lib/format";

const TURLER = ["positive", "negative", "boundary"] as const;
const RISKLER = ["high", "medium", "low"] as const;
const BOS_FILTRE = { ara: "", durum: "", tur: "", risk: "", gereksinim: "" };

/**
 * Tüm story'lerin test case'leri tek listede (story'den bağımsız case görünümü). Salt okunur:
 * karar (onay / düzeltme / ret) case'in story'sindeki "Case inceleme" ekranında verilir; satır oraya
 * götürür. Yerini yenisi almış (superseded) sürümler varsayılan olarak gizlidir.
 */
export function TestCaseleri() {
  const caseler = useVeri(() => api.caseler(), []);
  const gereksinimler = useVeri(() => api.gereksinimler(), []);
  const [filtre, setFiltre] = useState(BOS_FILTRE);
  const [eskiler, setEskiler] = useState(false);
  const sessizYenile = useGeciktirilmis(() => {
    void caseler.yenile(true);
    void gereksinimler.yenile(true);
  });
  useOlay(sessizYenile, ["case.generated", "case.updated", "requirement.updated"]);

  const gMap = useMemo(() => new Map((gereksinimler.veri ?? []).map((g) => [g.id, g])), [gereksinimler.veri]);
  const tum = caseler.veri ?? [];
  const guncel = useMemo(() => (eskiler ? tum : tum.filter((c) => c.durum !== "superseded")), [tum, eskiler]);
  // Story süzgecinde yalnız case'i olan story'ler listelenir.
  const storyler = useMemo(() => {
    const idler = [...new Set(guncel.map((c) => c.requirement_id))];
    return idler
      .map((id) => ({ id, ad: storyAdi(gMap.get(id), guncel.find((c) => c.requirement_id === id)) }))
      .sort((a, b) => a.ad.localeCompare(b.ad, "tr-TR"));
  }, [guncel, gMap]);

  const liste = useMemo(() => {
    const q = filtre.ara.trim().toLocaleLowerCase("tr-TR");
    return guncel
      .filter(
        (c) =>
          (!filtre.durum || c.durum === filtre.durum) &&
          (!filtre.tur || c.icerik.type === filtre.tur) &&
          (!filtre.risk || c.icerik.risk === filtre.risk) &&
          (!filtre.gereksinim || c.requirement_id === filtre.gereksinim) &&
          (!q ||
            [c.icerik.title, c.jira_key, c.jira_test_key, gMap.get(c.requirement_id)?.baslik, ...c.icerik.tags]
              .filter(Boolean)
              .join(" ")
              .toLocaleLowerCase("tr-TR")
              .includes(q)),
      )
      .sort(
        (a, b) =>
          storyAdi(gMap.get(a.requirement_id), a).localeCompare(storyAdi(gMap.get(b.requirement_id), b), "tr-TR") ||
          a.sira_no - b.sira_no,
      );
  }, [guncel, filtre, gMap]);

  const ayarla = (alan: keyof typeof BOS_FILTRE, deger: string) => setFiltre((f) => ({ ...f, [alan]: deger }));
  const suzuldu = Object.values(filtre).some(Boolean);
  const sayilar = useMemo(() => {
    const s: Partial<Record<CaseDurumu, number>> = {};
    for (const c of guncel) s[c.durum] = (s[c.durum] ?? 0) + 1;
    return s;
  }, [guncel]);

  return (
    <>
      <SayfaBasligi
        baslik="Test case'leri"
        aciklama="Tüm story'lerin test case'leri tek listede. Karar vermek ya da adımları görmek için case'in story'sindeki inceleme ekranına geçin."
      />
      <Kart>
        {caseler.yukleniyor && !caseler.veri ? (
          <Yukleniyor />
        ) : caseler.hata && !caseler.veri ? (
          <HataKutusu hata={caseler.hata} kaynak={caseler.hataNesnesi} yenile={() => void caseler.yenile()} />
        ) : tum.length === 0 ? (
          <BosDurum baslik="Henüz test case'i yok.">
            Case'ler, PO onaylı bir gereksinimden üretilir. <Link to="/gereksinimler">Gereksinimlere git</Link>
          </BosDurum>
        ) : (
          <>
            <div className="filtre-cubugu" role="group" aria-label="Test case süzgeci">
              <label>
                Ara
                <input
                  type="search"
                  placeholder="Başlık, anahtar veya etiket"
                  value={filtre.ara}
                  onChange={(e) => ayarla("ara", e.target.value)}
                />
              </label>
              <label>
                Story
                <select className="filtre-story" value={filtre.gereksinim} onChange={(e) => ayarla("gereksinim", e.target.value)}>
                  <option value="">Tümü</option>
                  {storyler.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.ad}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Durum
                <select value={filtre.durum} onChange={(e) => ayarla("durum", e.target.value)}>
                  <option value="">Tümü</option>
                  {CASE_DURUMLARI.filter((d) => eskiler || d !== "superseded").map((d) => (
                    <option key={d} value={d}>
                      {CASE_DURUMU[d].etiket}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Tür
                <select value={filtre.tur} onChange={(e) => ayarla("tur", e.target.value)}>
                  <option value="">Tümü</option>
                  {TURLER.map((t) => (
                    <option key={t} value={t}>
                      {CASE_TURU[t]}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Risk
                <select value={filtre.risk} onChange={(e) => ayarla("risk", e.target.value)}>
                  <option value="">Tümü</option>
                  {RISKLER.map((r) => (
                    <option key={r} value={r}>
                      {RISK[r].etiket}
                    </option>
                  ))}
                </select>
              </label>
              <label className="filtre-onay">
                <input
                  type="checkbox"
                  checked={eskiler}
                  onChange={(e) => {
                    setEskiler(e.target.checked);
                    if (!e.target.checked && filtre.durum === "superseded") ayarla("durum", "");
                  }}
                />
                Eski sürümleri göster
              </label>
              <span role="status" data-testid="case-sayisi">
                {suzuldu ? `${liste.length} / ${guncel.length} case` : `${guncel.length} case`}
                {CASE_DURUMLARI.filter((d) => sayilar[d]).map((d) => ` · ${sayilar[d]} ${CASE_DURUMU[d].etiket.toLocaleLowerCase("tr-TR")}`)}
              </span>
            </div>
            {liste.length === 0 ? (
              <BosDurum baslik="Süzgece uyan test case'i yok.">
                <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={() => setFiltre(BOS_FILTRE)}>
                  Süzgeci temizle
                </button>
              </BosDurum>
            ) : (
              <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Test case'leri tablosu">
                <table className="tablo tablo-yigin">
                  <thead>
                    <tr>
                      <th scope="col">Story</th>
                      <th scope="col" className="sayi">
                        No
                      </th>
                      <th scope="col">Başlık</th>
                      <th scope="col">Tür</th>
                      <th scope="col">Risk</th>
                      <th scope="col">Durum</th>
                      <th scope="col">Jira Test</th>
                      <th scope="col">Son karar</th>
                    </tr>
                  </thead>
                  <tbody>
                    {liste.map((c) => (
                      <CaseSatiri key={c.id} c={c} g={gMap.get(c.requirement_id)} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Kart>
    </>
  );
}

function storyAdi(g: Gereksinim | undefined, c: TestCase | undefined): string {
  const anahtar = g?.jira_key ?? c?.jira_key ?? null;
  if (g) return anahtar ? `${anahtar} · ${g.baslik}` : g.baslik;
  return anahtar ?? "Serbest metin gereksinim";
}

function CaseSatiri({ c, g }: { c: TestCase; g: Gereksinim | undefined }) {
  const durum = CASE_DURUMU[c.durum];
  const risk = RISK[c.icerik.risk];
  const gYolu = `/gereksinimler/${encodeURIComponent(c.requirement_id)}`;
  const testAdresi = guvenliDisAdres(c.jira_test_url);
  return (
    <tr>
      <td className="tek-satir" data-etiket="Story">
        <Link to={gYolu} title={g?.baslik}>
          {g?.jira_key ?? c.jira_key ?? g?.baslik ?? "Serbest metin"}
        </Link>
      </td>
      <td className="sayi mono" data-etiket="No">
        #{c.sira_no}
      </td>
      <td data-etiket="Başlık">
        <Link to={`${gYolu}/caseler`} className="satir-baglanti">
          {c.icerik.title}
        </Link>
        {c.kanal === "ide" && <span className="soluk"> · IDE kanalı</span>}
      </td>
      <td data-etiket="Tür">{CASE_TURU[c.icerik.type] ?? c.icerik.type}</td>
      <td data-etiket="Risk">{risk ? <Cip ton={risk.ton}>{risk.etiket}</Cip> : c.icerik.risk}</td>
      <td data-etiket="Durum">
        <Cip ton={durum.ton}>{durum.etiket}</Cip>
      </td>
      <td className="mono" data-etiket="Jira Test">
        {!c.jira_test_key ? "—" : testAdresi ? <DisBaglanti href={testAdresi}>{c.jira_test_key}</DisBaglanti> : c.jira_test_key}
      </td>
      <td className="tek-satir" data-etiket="Son karar">
        {c.karar_zamani ? tarih(c.karar_zamani) : "—"}
      </td>
    </tr>
  );
}
