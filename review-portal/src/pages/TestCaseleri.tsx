import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import { CASE_DURUMLARI, type CaseDurumu, type Gereksinim, type Script, type TestCase } from "../api/types";
import { caseCapasi } from "../components/CaseKarti";
import { DilRozeti } from "../components/Dil";
import { PlatformRozeti } from "../components/Platform";
import { BosDurum, Cip, DisBaglanti, HataKutusu, IzinliLink, Kart, SayfaBasligi, Yukleniyor } from "../components/ui";
import { useIzin } from "../auth";
import { useGeciktirilmis, useVeri } from "../hooks";
import { CASE_DURUMU, CASE_TURU, RISK, SCRIPT_DURUMU } from "../lib/etiketler";
import { guvenliDisAdres, tarih } from "../lib/format";

const TURLER = ["positive", "negative", "boundary"] as const;
const RISKLER = ["high", "medium", "low"] as const;
const BOS_FILTRE = { ara: "", durum: "", tur: "", risk: "", gereksinim: "" };

/**
 * Case'in otomasyon durumu: kapatılmamış script'leri (platform + dil, durum, PR). Veri `GET /scripts`
 * listesinden istemci tarafında eşlenir (ek uç yok). Liste yüklenemezse null: hücre "—" der, uydurmaz.
 */
export function caseScriptleri(scriptler: readonly Script[] | null): Map<string, Script[]> | null {
  if (!scriptler) return null;
  const m = new Map<string, Script[]>();
  for (const s of scriptler) {
    if (s.durum === "closed") continue;
    for (const id of s.case_ids) m.set(id, [...(m.get(id) ?? []), s]);
  }
  return m;
}

/**
 * Tüm story'lerin test case'leri tek listede (story'den bağımsız case görünümü). Salt okunur:
 * karar (onay / düzeltme / ret) case'in story'sindeki "Case inceleme" ekranında verilir; satır doğrudan
 * o case'in kartına götürür (`#case-<id>` çapası). Yerini yenisi almış (superseded) sürümler varsayılan
 * olarak gizlidir. "Otomasyon" sütunu case'in kodunu (platform, dil, durum, PR) gösterir.
 */
export function TestCaseleri() {
  const caseler = useVeri(() => api.caseler(), []);
  const gereksinimler = useVeri(() => api.gereksinimler(), []);
  // QA-Y4: core listeyi en yeni 200 kayıtla sınırlar; sınıra ulaşıldıysa eşleşmeyen case "bilinmiyor"dur.
  // 012: script listesi `code.read` ister; izni olmayan rolde (PO, developer) istenmez, sütun "—" der.
  const kodOkur = useIzin("code.read");
  const scriptler = useVeri(() => (kodOkur ? api.scriptListesi() : Promise.resolve(null)), [kodOkur]);
  const [filtre, setFiltre] = useState(BOS_FILTRE);
  const [eskiler, setEskiler] = useState(false);
  const sessizYenile = useGeciktirilmis(() => {
    void caseler.yenile(true);
    void gereksinimler.yenile(true);
    void scriptler.yenile(true);
  });
  useOlay(sessizYenile, ["case.generated", "case.updated", "requirement.updated", "script.updated", "pr.opened", "pr.merged"]);
  const otomasyon = useMemo(() => caseScriptleri(scriptler.veri?.kayitlar ?? null), [scriptler.veri]);
  const listeSinirda = !!scriptler.veri?.sinira_ulasti;

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
        aciklama="Tüm story'lerin test case'leri tek listede. Karar vermek ya da adımları görmek için başlığa tıklayın: case'in story'sindeki inceleme ekranında o case açılır."
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
            {/* Dokunmatik ekranda title görünmez: sınır bilgisi listenin üstünde bir kez yazılır. */}
            {listeSinirda && (
              <p className="kucuk soluk" data-testid="otomasyon-sinir-notu">
                Otomasyon sütunu en yeni 200 script kaydından eşlenir; eşleşmeyen case'lerde "Bilinmiyor" yazar (daha eski bir kodu olabilir).
              </p>
            )}
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
                      <th scope="col">Otomasyon</th>
                      <th scope="col">Son karar</th>
                    </tr>
                  </thead>
                  <tbody>
                    {liste.map((c) => (
                      <CaseSatiri key={c.id} c={c} g={gMap.get(c.requirement_id)} scriptler={otomasyon ? (otomasyon.get(c.id) ?? []) : null} sinirda={listeSinirda} />
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

/** Liste sınırına ulaşıldığında eşleşmeyen case'in açıklaması (title + ekran okuyucu). */
export const OTOMASYON_BILINMIYOR =
  "Kod listesi en yeni 200 kayıtla sınırlı; bu case'in listede görünmeyen daha eski bir kodu olabilir.";

function OtomasyonHucresi({ scriptler, sinirda }: { scriptler: Script[] | null; sinirda: boolean }) {
  if (scriptler === null) return <span className="soluk">—</span>;
  if (scriptler.length === 0)
    return sinirda ? (
      <span className="soluk kucuk otomasyon-bilinmiyor" title={OTOMASYON_BILINMIYOR} data-testid="otomasyon-bilinmiyor">
        Bilinmiyor<span className="gorunmez">: {OTOMASYON_BILINMIYOR}</span>
      </span>
    ) : (
      <span className="soluk kucuk">Kod yok</span>
    );
  return (
    <ul className="duz-liste otomasyon-liste">
      {scriptler.map((s) => {
        const d = SCRIPT_DURUMU[s.durum] ?? { etiket: s.durum, ton: "notr" as const };
        return (
          <li key={s.id} className="satir-ogeler kucuk" data-testid="otomasyon-script">
            <PlatformRozeti platform={s.platform} />
            <DilRozeti dil={s.dil} platform={s.platform} />
            <Cip ton={d.ton}>{d.etiket}</Cip>
            {/* Script ekranı (`/kod/:id`, `code.read`); PR numarası o ekranın PR kartına götürür. */}
            {s.pr ? (
              <IzinliLink to={`/kod/${encodeURIComponent(s.id)}#pr`} className="mono" data-testid="otomasyon-pr">
                PR #{s.pr.number}{" "}
                <span className="gorunmez">({s.pr.durum === "merged" ? "birleşti" : s.pr.durum === "open" ? "açık" : "kapalı"}) · script</span>
              </IzinliLink>
            ) : (
              <IzinliLink to={`/kod/${encodeURIComponent(s.id)}`} data-testid="otomasyon-script-baglanti">
                Script
              </IzinliLink>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function CaseSatiri({ c, g, scriptler, sinirda }: { c: TestCase; g: Gereksinim | undefined; scriptler: Script[] | null; sinirda: boolean }) {
  const durum = CASE_DURUMU[c.durum];
  const risk = c.icerik.risk ? RISK[c.icerik.risk] : undefined;
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
        <Link to={`${gYolu}/caseler#${encodeURIComponent(caseCapasi(c.id))}`} className="satir-baglanti">
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
      <td data-etiket="Otomasyon">
        <OtomasyonHucresi scriptler={scriptler} sinirda={sinirda} />
      </td>
      <td className="tek-satir" data-etiket="Son karar">
        {c.karar_zamani ? tarih(c.karar_zamani) : "—"}
      </td>
    </tr>
  );
}
