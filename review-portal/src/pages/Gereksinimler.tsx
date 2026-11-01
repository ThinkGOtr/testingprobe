import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { Gereksinim } from "../api/types";
import { useBildirim } from "../components/Bildirim";
import { BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, SayfaBasligi, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { adimAdi, akisAdimi } from "../lib/akis";
import { akisKanitlari, guncelAdim, type SonrakiGirdi } from "../lib/yolHaritasi";
import { AC_EKSIK, AKIS_ADIMLARI, gereksinimDurumu } from "../lib/etiketler";
import { tarih } from "../lib/format";
import { ORNEK_SERBEST_GEREKSINIM } from "../lib/ornekGereksinim";

const PO_ETIKET = { not_requested: "—", pending: "Bekliyor", approved: "Onaylı" } as const;

export function Gereksinimler() {
  const { veri, hata, yukleniyor, yenile } = useVeri(() => api.gereksinimler(), []);
  // `done` story'lerin kod → bug adımları (5–14) yol haritasıyla aynı kanıtlardan okunur.
  const tamamVar = (veri ?? []).some((g) => g.durum === "done");
  const kanit = useVeri(() => (tamamVar ? akisKanitlari() : Promise.resolve(null)), [tamamVar]);
  const [formAcik, setFormAcik] = useState(false);
  const [filtre, setFiltre] = useState("");
  const cek = useIslem();
  const bildir = useBildirim();
  const sessizYenile = useGeciktirilmis(() => void yenile(true));
  useOlay(sessizYenile, ["requirement.updated", "case.generated"]);

  const liste = useMemo(() => {
    const q = filtre.trim().toLocaleLowerCase("tr-TR");
    if (!veri || !q) return veri ?? [];
    return veri.filter((g) => `${g.jira_key ?? ""} ${g.baslik}`.toLocaleLowerCase("tr-TR").includes(q));
  }, [veri, filtre]);

  return (
    <>
      <SayfaBasligi
        baslik="Gereksinimler"
        aciklama="Jira story'leri ve serbest metin gereksinimler. Her biri 14 adımlı akışta ilerler; insan kapıları atlanamaz."
        eylemler={
          <>
            <IslemDugmesi
              roller={["analyst"]}
              tur="ikincil"
              calisiyor={cek.calisiyor}
              onClick={async () => {
                const s = await cek.calistir(() => api.jiradanCek());
                if (s) {
                  bildir(s.mesaj ?? "Jira'dan çekim başlatıldı.");
                  void yenile(true);
                }
              }}
            >
              Jira'dan çek
            </IslemDugmesi>
            <IslemDugmesi roller={["analyst"]} onClick={() => setFormAcik((a) => !a)} aria-expanded={formAcik} aria-controls="serbest-metin">
              {formAcik ? "Formu kapat" : "Serbest metin gereksinim"}
            </IslemDugmesi>
          </>
        }
      />
      {cek.hata && <HataKutusu hata={cek.hata} />}
      {formAcik && <SerbestMetinFormu kapat={() => setFormAcik(false)} />}

      <Kart
        baslik="Gereksinim listesi"
        eylemler={
          <div className="alan alan-satir">
            <label htmlFor="gereksinim-ara" className="gorunmez">
              Gereksinim ara
            </label>
            <input id="gereksinim-ara" type="search" placeholder="Anahtar veya başlık ara" value={filtre} onChange={(e) => setFiltre(e.target.value)} />
          </div>
        }
      >
        {yukleniyor && !veri ? (
          <Yukleniyor />
        ) : hata && !veri ? (
          <HataKutusu hata={hata} yenile={() => void yenile()} />
        ) : liste.length === 0 ? (
          <BosDurum baslik={filtre ? "Aramaya uyan gereksinim yok." : "Henüz gereksinim yok."}>
            {!filtre && "Jira'dan çekin veya serbest metin gereksinim ekleyin."}
          </BosDurum>
        ) : (
          <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Gereksinimler tablosu">
            <table className="tablo tablo-yigin">
              <thead>
                <tr>
                  <th scope="col">Anahtar</th>
                  <th scope="col">Başlık</th>
                  <th scope="col">Durum</th>
                  <th scope="col">Adım</th>
                  <th scope="col">PO</th>
                  <th scope="col" className="sayi">
                    Açık bulgu
                  </th>
                  <th scope="col" className="sayi">
                    Case (onaylı/toplam)
                  </th>
                  <th scope="col">Çekim</th>
                </tr>
              </thead>
              <tbody>
                {liste.map((g) => (
                  <GereksinimSatiri key={g.id} g={g} kanit={kanit.veri ?? null} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Kart>
    </>
  );
}

function GereksinimSatiri({ g, kanit }: { g: Gereksinim; kanit: Omit<SonrakiGirdi, "gereksinim"> | null }) {
  // Kabul kriteri yoksa core durumu `new` kalır; asıl engel AC eksikliği olduğu için o gösterilir.
  const d = g.ac_missing && g.durum === "new" ? AC_EKSIK : gereksinimDurumu(g.durum);
  const adim = guncelAdim(g, kanit, akisAdimi(g.durum, g.adim));
  const akisTamam = adim > AKIS_ADIMLARI.length;
  return (
    <tr>
      <td className="mono" data-etiket="Anahtar">
        {g.jira_key ?? (
          <Cip ton="vurgu" title="Serbest metin gereksinim">
            Serbest metin
          </Cip>
        )}
      </td>
      <td data-etiket="Başlık">
        <Link to={`/gereksinimler/${encodeURIComponent(g.id)}`} className="satir-baglanti">
          {g.baslik}
        </Link>
        {g.ac_missing && <span className="soluk"> · kabul kriteri yok</span>}
      </td>
      <td data-etiket="Durum">
        <Cip ton={d.ton}>{d.etiket}</Cip>
      </td>
      <td data-etiket="Adım">
        <span className="mono">
          {Math.min(adim, AKIS_ADIMLARI.length)}/{AKIS_ADIMLARI.length}
        </span>{" "}
        <span className="soluk">{akisTamam ? "akış tamam" : adimAdi(adim, g.kaynak)}</span>
      </td>
      <td data-etiket="PO">{PO_ETIKET[g.po.durum]}</td>
      <td className="sayi" data-etiket="Açık bulgu">
        {!g.sayaclar.bulgu_acik ? (
          "—"
        ) : g.durum === "findings_open" || g.durum === "in_review" ? (
          g.sayaclar.bulgu_acik
        ) : (
          <span className="soluk" title="Gereksinim bulgu kararı beklemiyor; kalan uyarılar bilgi amaçlıdır">
            {g.sayaclar.bulgu_acik} uyarı
          </span>
        )}
      </td>
      <td className="sayi" data-etiket="Case (onaylı)">
        {g.sayaclar.case_toplam ? `${g.sayaclar.case_onayli}/${g.sayaclar.case_toplam}` : "—"}
      </td>
      <td data-etiket="Çekim">{tarih(g.cekim_zamani)}</td>
    </tr>
  );
}

function SerbestMetinFormu({ kapat }: { kapat: () => void }) {
  const [baslik, setBaslik] = useState("");
  const [aciklama, setAciklama] = useState("");
  const [acler, setAcler] = useState<string[]>([""]);
  const [dogrulama, setDogrulama] = useState<string | null>(null);
  const islem = useIslem();
  const git = useNavigate();
  const bildir = useBildirim();

  async function gonder(e: FormEvent) {
    e.preventDefault();
    if (baslik.trim().length < 3) return setDogrulama("Başlık en az 3 karakter olmalı.");
    if (!aciklama.trim()) return setDogrulama("Açıklama zorunlu.");
    setDogrulama(null);
    const g = await islem.calistir(() =>
      api.serbestMetin({ baslik: baslik.trim(), aciklama: aciklama.trim(), ac: acler.map((a) => a.trim()).filter(Boolean) }),
    );
    if (g) {
      bildir("Serbest metin gereksinim oluşturuldu.");
      kapat();
      git(`/gereksinimler/${encodeURIComponent(g.id)}`);
    }
  }

  return (
    <Kart baslik="Serbest metin gereksinim" id="serbest-metin">
      <p className="soluk">
        Jira dışı gereksinimler için. PO teyidi bu yolda portalda (PO rolüyle) verilir; sonrası aynı akış.
      </p>
      <div className="satir-ogeler">
        <IslemDugmesi
          roller={["analyst", "presenter"]}
          tur="ikincil"
          kucuk
          onClick={() => {
            setBaslik(ORNEK_SERBEST_GEREKSINIM.baslik);
            setAciklama(ORNEK_SERBEST_GEREKSINIM.aciklama);
            setAcler([...ORNEK_SERBEST_GEREKSINIM.ac]);
            setDogrulama(null);
          }}
        >
          Örnek gereksinimi doldur
        </IslemDugmesi>
        <span className="soluk kucuk">
          Demo metni kayıtlı (REPLAY) çıktıyla birebir eşleşir. Metni değiştirirseniz AI adımları dürüstçe REPLAY-MISS olarak
          işaretlenir.
        </span>
      </div>
      <form onSubmit={gonder} className="form" noValidate>
        <div className="alan">
          <label htmlFor="ft-baslik">Başlık</label>
          <input id="ft-baslik" value={baslik} maxLength={200} onChange={(e) => setBaslik(e.target.value)} required />
        </div>
        <div className="alan">
          <label htmlFor="ft-aciklama">Açıklama</label>
          <textarea id="ft-aciklama" rows={3} value={aciklama} onChange={(e) => setAciklama(e.target.value)} required />
        </div>
        <fieldset className="alan">
          <legend>Kabul kriterleri</legend>
          {acler.map((ac, i) => (
            <div key={i} className="ac-satir">
              <label htmlFor={`ft-ac-${i}`} className="mono ac-etiket">
                AC{i + 1}
              </label>
              <input
                id={`ft-ac-${i}`}
                value={ac}
                onChange={(e) => setAcler((l) => l.map((x, j) => (j === i ? e.target.value : x)))}
              />
              <button
                type="button"
                className="dugme dugme-hayalet dugme-kucuk"
                aria-label={`AC${i + 1} kaldır`}
                onClick={() => setAcler((l) => (l.length > 1 ? l.filter((_, j) => j !== i) : [""]))}
              >
                Kaldır
              </button>
            </div>
          ))}
          <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={() => setAcler((l) => [...l, ""])}>
            Kabul kriteri ekle
          </button>
          <p className="soluk kucuk">Kabul kriteri girilmezse gereksinim "AC eksik" olarak işaretlenir ve case üretimine gönderilmez.</p>
        </fieldset>
        {(dogrulama || islem.hata) && (
          <p className="alan-hata" role="alert">
            {dogrulama ?? islem.hata}
          </p>
        )}
        <div className="eylemler">
          <IslemDugmesi roller={["analyst"]} type="submit" calisiyor={islem.calisiyor}>
            Gereksinimi oluştur
          </IslemDugmesi>
          <button type="button" className="dugme dugme-hayalet" onClick={kapat}>
            Vazgeç
          </button>
        </div>
      </form>
    </Kart>
  );
}
