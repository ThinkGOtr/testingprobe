// TP UX denetimi IA-01: "İşlerim" — rolün kuyruğu. Bana düşen işler (rolün insan kapıları), her
// öğede neden bekliyor + sıradaki adım + bağlantı; başka rollere düşenler ayrı "Ekipte bekleyenler"
// grubunda (kimi bekliyoruz). Kaynak `GET /work-queue` (core `features/islerim`).
import { Link } from "react-router-dom";
import { useOlay } from "../api/events";
import { islerimApi, type IsGrubu, type IsOgesi } from "../api/islerim";
import { useKisiAdi, useOturum } from "../auth";
import { BosDurum, Cip, HataKutusu, Kart, SayfaBasligi, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useVeri } from "../hooks";
import { tarih } from "../lib/format";
import { ROL_ETIKETLERI, rolEtiketi } from "../lib/yetki";

/** Kuyruğu tazeleyen olaylar (karar, üretim, PR, triage, yayın). */
export const ISLERIM_OLAYLARI = [
  "requirement.updated",
  "finding.updated",
  "case.generated",
  "case.updated",
  "case.review",
  "publish.updated",
  "script.updated",
  "pr.opened",
  "pr.merged",
  "ci.status",
  "failure.classified",
  "failure.updated",
  "bug.draft_created",
  "bug.published",
] as const;

const TUR_ADI: Record<string, string> = {
  requirement: "Gereksinim",
  case: "Case",
  script: "Script",
  run: "Koşu",
  failure: "Hata",
  bug_draft: "Bug taslağı",
};

function OgeSatiri({ o }: { o: IsOgesi }) {
  return (
    <li className="islerim-oge">
      <div className="islerim-oge-govde">
        <Link to={o.rota} className="islerim-oge-baslik">
          {o.etiket}
        </Link>
        <span className="soluk kucuk">
          {o.neden}
          {o.zaman && <> · {tarih(o.zaman)}</>}
        </span>
      </div>
      <Link to={o.rota} className="dugme dugme-ikincil dugme-kucuk" aria-label={`${o.etiket}: aç`}>
        Aç →
      </Link>
    </li>
  );
}

/** Katlanan satır: aynı nedenle düşen öğeler (ör. 13 koşu "Testler koşmadı: CI ortam hatası"). */
export interface KatliSatir {
  neden: string;
  ogeler: IsOgesi[];
}

/**
 * Koşu grubunda aynı nedenle düşen öğeler tek satıra katlanır (≥2 öğe; ilk görünme sırası korunur).
 * Koşu etiketi ("PR koşusu") ayırt edici olmadığından kuyruğu şişiriyordu; diğer türlerde etiket
 * kaydın kendisidir, katlanmaz.
 */
export function nedeneGoreKatla(g: Pick<IsGrubu, "tur" | "ogeler">): (IsOgesi | KatliSatir)[] {
  if (g.tur !== "run") return g.ogeler;
  const kume = new Map<string, IsOgesi[]>();
  for (const o of g.ogeler) {
    const l = kume.get(o.neden);
    if (l) l.push(o);
    else kume.set(o.neden, [o]);
  }
  const out: (IsOgesi | KatliSatir)[] = [];
  const yazildi = new Set<string>();
  for (const o of g.ogeler) {
    const l = kume.get(o.neden)!;
    if (l.length < 2) out.push(o);
    else if (!yazildi.has(o.neden)) {
      yazildi.add(o.neden);
      out.push({ neden: o.neden, ogeler: l });
    }
  }
  return out;
}

function KatliSatiri({ k, tur }: { k: KatliSatir; tur: string }) {
  const son = k.ogeler.find((o) => o.zaman)?.zaman;
  const ad = tur === "run" ? "koşu" : "öğe";
  return (
    <li className="islerim-oge islerim-katli" data-testid="islerim-katli">
      <details>
        <summary>
          <span className="islerim-oge-baslik">
            {k.ogeler.length} {ad}: {k.neden}
          </span>
          {son && <span className="soluk kucuk"> · en son {tarih(son)}</span>}
        </summary>
        <ul className="duz-liste islerim-liste" aria-label={`${k.neden}: ${k.ogeler.length} ${ad}`}>
          {k.ogeler.map((o) => (
            <OgeSatiri key={`${o.tur}-${o.id}`} o={o} />
          ))}
        </ul>
      </details>
    </li>
  );
}

function BenimGrubum({ g }: { g: IsGrubu }) {
  const kalan = g.oge_sayisi - g.ogeler.length;
  return (
    <Kart
      baslik={
        <>
          {g.baslik} <Cip ton="bilgi">{g.sayi}</Cip>
        </>
      }
      className="islerim-grup"
    >
      <p className="islerim-sonraki">
        <strong>Sıradaki adım:</strong> {g.sonraki_adim}
      </p>
      <ul className="duz-liste islerim-liste" aria-label={g.baslik}>
        {nedeneGoreKatla(g).map((o) =>
          "id" in o ? <OgeSatiri key={`${o.tur}-${o.id}`} o={o} /> : <KatliSatiri key={`katli-${o.neden}`} k={o} tur={g.tur} />,
        )}
      </ul>
      {kalan > 0 && <p className="soluk kucuk">ve {kalan} öğe daha (ilgili listede).</p>}
    </Kart>
  );
}

/** "Gokhan Sipahi (AI Probe) · Analist" → "Gokhan Sipahi (AI Probe)": rol zaten satırda yazılı (YD-05). */
export function rolEkiniAt(ad: string): string {
  for (const e of Object.values(ROL_ETIKETLERI)) if (ad.endsWith(` · ${e}`)) return ad.slice(0, -(e.length + 3)).trim() || ad;
  return ad;
}

function EkipGrubu({ g }: { g: IsGrubu }) {
  const kisiAdi = useKisiAdi();
  const kisiler = [...new Set((g.kisiler ?? []).map((k) => rolEkiniAt(kisiAdi(k))).filter(Boolean))];
  return (
    <li className="islerim-ekip-satiri">
      <div className="islerim-oge-govde">
        <span>
          <strong>{g.baslik}</strong> <Cip ton="notr">{g.sayi}</Cip>
        </span>
        <span className="soluk kucuk">
          {g.rol_etiketi} bekleniyor{kisiler.length > 0 && <> ({kisiler.join(", ")})</>} · {TUR_ADI[g.tur] ?? g.tur}
        </span>
        {g.ogeler.length > 0 && (
          <ul className="duz-liste islerim-ekip-ogeleri" aria-label={`${g.baslik}: öğeler`}>
            {g.ogeler.map((o) => (
              <li key={`${o.tur}-${o.id}`}>
                <Link to={o.rota}>{o.etiket}</Link> <span className="soluk kucuk">· {o.neden}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

export function Islerim() {
  const { kullanici } = useOturum();
  const v = useVeri(() => islerimApi.isKuyrugu(), [kullanici?.rol]);
  const sessiz = useGeciktirilmis(() => void v.yenile(true));
  useOlay(sessiz, ISLERIM_OLAYLARI);
  const k = v.veri;
  const rol = k?.rol_etiketi || (kullanici ? rolEtiketi(kullanici.rol) : "");

  return (
    <>
      <SayfaBasligi
        baslik="İşlerim"
        aciklama={
          k
            ? `${rol} olarak sizi bekleyen ${k.toplam} iş · ekipte bekleyen ${k.ekip_toplam} iş`
            : "Rolünüze düşen işler ve ekipte kimi beklediğimiz."
        }
      />
      {v.yukleniyor && !k ? (
        <Yukleniyor />
      ) : v.hata && !k ? (
        <HataKutusu hata={v.hata} kaynak={v.hataNesnesi} yenile={() => void v.yenile()} />
      ) : k ? (
        <>
          <section aria-labelledby="islerim-benim" className="islerim-bolum">
            <h2 id="islerim-benim" className="islerim-bolum-baslik">
              Sizi bekleyenler
            </h2>
            {k.benim.length === 0 ? (
              <Kart>
                <BosDurum baslik="Şu an sizi bekleyen iş yok.">
                  {k.ekip.length > 0
                    ? "Akış ekipte ilerliyor; aşağıda kimi beklediğimizi görebilirsiniz."
                    : "Yeni iş, bir gereksinim Jira'dan çekildiğinde ya da bir koşu bittiğinde burada görünür. "}
                  {k.ekip.length === 0 && <Link to="/gereksinimler">Gereksinimlere git</Link>}
                </BosDurum>
              </Kart>
            ) : (
              k.benim.map((g) => <BenimGrubum key={g.anahtar} g={g} />)
            )}
          </section>
          {k.ekip.length > 0 && (
            <section aria-labelledby="islerim-ekip" className="islerim-bolum">
              <h2 id="islerim-ekip" className="islerim-bolum-baslik">
                Ekipte bekleyenler
              </h2>
              <Kart>
                <ul className="duz-liste islerim-liste">
                  {k.ekip.map((g) => (
                    <EkipGrubu key={g.anahtar} g={g} />
                  ))}
                </ul>
              </Kart>
            </section>
          )}
        </>
      ) : null}
    </>
  );
}
