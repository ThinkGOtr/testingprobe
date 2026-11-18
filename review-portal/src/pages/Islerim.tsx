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
import { icTerimleriAyikla, testAdiGoster } from "../lib/etiketler";
import { rolEtiketi } from "../lib/yetki";

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
          {testAdiGoster(o.etiket)}
        </Link>
        <span className="soluk kucuk">
          {/* CL-07: iç kodlar (S4:, REPLAY-MISS:, @tp-…) gösterimde ayıklanır. */}
          {icTerimleriAyikla(o.neden)}
          {o.zaman && <> · {tarih(o.zaman)}</>}
        </span>
      </div>
      <Link to={o.rota} className="dugme dugme-ikincil dugme-kucuk" aria-label={`${testAdiGoster(o.etiket)}: aç`}>
        Aç →
      </Link>
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
        {g.ogeler.map((o) => (
          <OgeSatiri key={`${o.tur}-${o.id}`} o={o} />
        ))}
      </ul>
      {kalan > 0 && <p className="soluk kucuk">ve {kalan} öğe daha (ilgili listede).</p>}
    </Kart>
  );
}

function EkipGrubu({ g }: { g: IsGrubu }) {
  const kisiAdi = useKisiAdi();
  const kisiler = (g.kisiler ?? []).map((k) => kisiAdi(k)).filter(Boolean);
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
                <Link to={o.rota}>{testAdiGoster(o.etiket)}</Link> <span className="soluk kucuk">· {icTerimleriAyikla(o.neden)}</span>
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
