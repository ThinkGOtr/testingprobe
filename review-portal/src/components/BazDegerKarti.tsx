// Story başına manuel test tasarımı baz değeri (TEKNIK-TASARIM §12 "Hazırlık süresi", Faz 5).
// Değer yalnızca gerçek bir ölçümden girilir (kim, ne zaman, not); portal tahmin önermez,
// varsayılan değeri ölçüm gibi göstermez. Kazanç Kontrol Kulesi'nde yalnızca ölçülmüş story'lerde.
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { BazKaynagi, GereksinimDetay, ManuelBaz } from "../api/types";
import { BAZ_NOT_EN_AZ, BAZ_NOT_EN_COK, BAZ_UST_SINIR_S } from "../api/uyumFaz5";
import { useRol } from "../auth";
import { useIslem } from "../hooks";
import { KisiAdi } from "./KisiAdi";
import { sure, tarih } from "../lib/format";
import type { Ton } from "../lib/etiketler";
import { useBildirim } from "./Bildirim";
import { Cip, HataKutusu, IslemDugmesi, Kart } from "./ui";

export const BAZ_KAYNAGI: Record<BazKaynagi, { etiket: string; ton: Ton; aciklama: string }> = {
  olcum: { etiket: "Ölçüm", ton: "basari", aciklama: "Bu story için elle ölçülüp girildi; kazanç bu değerle hesaplanır." },
  varsayilan: {
    etiket: "Varsayılan",
    ton: "bilgi",
    aciklama: "Ortam ayarı (TP_MANUAL_BASELINE_S); bu story için ölçülmedi. Kazanç hesabına girmez.",
  },
  olculmedi: { etiket: "Ölçülmedi", ton: "notr", aciklama: "Baz değer yok; kazanç hesaplanmaz." },
};

/** Form girdisi (dakika + saniye + not) → istek gövdesi ya da Türkçe doğrulama hatası. */
export function bazFormuDogrula(dk: string, sn: string, not: string, gercekOlcum: boolean): { deger_s: number; not: string } | { hata: string } {
  const tamSayi = (x: string) => (x.trim() === "" ? 0 : /^\d+$/.test(x.trim()) ? Number(x.trim()) : NaN);
  const d = tamSayi(dk);
  const s = tamSayi(sn);
  if (Number.isNaN(d) || Number.isNaN(s)) return { hata: "Dakika ve saniye negatif olmayan tam sayı olmalı." };
  if (s > 59) return { hata: "Saniye 0–59 arasında olmalı." };
  const toplam = d * 60 + s;
  if (toplam < 1) return { hata: "Ölçülen süre girilmedi." };
  if (toplam > BAZ_UST_SINIR_S) return { hata: `Süre en fazla ${BAZ_UST_SINIR_S / 3600} saat olabilir.` };
  const n = not.trim();
  // Core ile aynı kural: boşluk dışındaki karakter sayılır ("a b" yetmez).
  if (n.replace(/\s/g, "").length < BAZ_NOT_EN_AZ) return { hata: "Ölçüm notu gerekli: kim, hangi yöntemle ölçtü (ör. \"İsmail, F0 kronometre, 4 story ortalaması değil\")." };
  if (n.length > BAZ_NOT_EN_COK) return { hata: `Ölçüm notu en fazla ${BAZ_NOT_EN_COK} karakter olabilir.` };
  if (!gercekOlcum) return { hata: "Değerin gerçek bir ölçümden geldiğini onaylayın; tahmin girilmez." };
  return { deger_s: toplam, not: n };
}

function BazDegeri({ b }: { b: ManuelBaz }) {
  const k = BAZ_KAYNAGI[b.kaynak];
  return (
    <div data-testid="baz-deger">
      <p className="satir-ogeler">
        <span className="buyuk-sayi-kucuk" data-testid="baz-deger-sure">
          {b.deger_s === null ? <span className="olculmedi">ölçülmedi</span> : sure(b.deger_s * 1000)}
        </span>
        <Cip ton={k.ton} title={k.aciklama}>
          {k.etiket}
        </Cip>
      </p>
      <p className="soluk kucuk">{k.aciklama}</p>
      {b.kaynak === "olcum" && (
        <dl className="tanim-izgara kucuk">
          <dt>Giren</dt>
          <dd>{b.giren ? <KisiAdi ad={b.giren} /> : "—"}</dd>
          <dt>Zaman</dt>
          <dd>{tarih(b.zaman)}</dd>
          <dt>Not</dt>
          <dd className="baz-not">{b.not ?? "—"}</dd>
        </dl>
      )}
    </div>
  );
}

export function BazDegerKarti({ g, guncellendi }: { g: Pick<GereksinimDetay, "id" | "manuel_baz">; guncellendi: (b: ManuelBaz | undefined) => void }) {
  const yetkili = useRol("analyst", "po");
  const islem = useIslem();
  const bildir = useBildirim();
  const [acik, setAcik] = useState(false);
  const [dk, setDk] = useState("");
  const [sn, setSn] = useState("");
  const [not, setNot] = useState("");
  const [gercek, setGercek] = useState(false);
  const [dogrulamaHatasi, setDogrulamaHatasi] = useState<string | null>(null);
  const [silOnayi, setSilOnayi] = useState(false);
  const b = g.manuel_baz;

  function formuAc() {
    const mevcut = b?.kaynak === "olcum" && b.deger_s !== null ? b.deger_s : null;
    setDk(mevcut === null ? "" : String(Math.floor(mevcut / 60)));
    setSn(mevcut === null ? "" : String(mevcut % 60));
    setNot(b?.kaynak === "olcum" ? (b.not ?? "") : "");
    setGercek(false);
    setDogrulamaHatasi(null);
    islem.temizle();
    setAcik(true);
  }

  async function kaydet(e: FormEvent) {
    e.preventDefault();
    const d = bazFormuDogrula(dk, sn, not, gercek);
    if ("hata" in d) {
      setDogrulamaHatasi(d.hata);
      return;
    }
    setDogrulamaHatasi(null);
    let basarili = false;
    const s = await islem.calistir(async () => {
      const y = await api.bazDegerKaydet(g.id, d);
      basarili = true;
      return y;
    });
    if (basarili) {
      // Yanıt baz değer taşımıyorsa (undefined) çağıran detayı yeniden okur.
      guncellendi(s);
      bildir("Manuel baz değer kaydedildi.");
      setAcik(false);
    }
  }

  async function sil() {
    let basarili = false;
    const s = await islem.calistir(async () => {
      const y = await api.bazDegerSil(g.id);
      basarili = true;
      return y;
    });
    if (basarili) {
      guncellendi(s);
      bildir("Manuel baz değer silindi.");
      setSilOnayi(false);
    }
  }

  return (
    <Kart
      baslik="Manuel baz değer"
      eylemler={
        b !== undefined &&
        !acik && (
          <IslemDugmesi roller={["analyst", "po"]} tur="ikincil" kucuk onClick={formuAc}>
            {b.kaynak === "olcum" ? "Ölçümü düzenle" : "Ölçüm gir"}
          </IslemDugmesi>
        )
      }
    >
      <p className="soluk kucuk">
        Bu story için manuel test case hazırlamanın ölçülen süresi (TEKNIK-TASARIM §12). Kontrol Kulesi'ndeki hazırlık kazancı yalnızca
        ölçülmüş story'lerde hesaplanır; değer tahmin edilmez.
      </p>
      {b === undefined ? (
        <p className="kucuk" data-testid="baz-deger-yok">
          <span className="olculmedi">bilinmiyor</span> Çekirdek bu story için baz değer bilgisini henüz sunmuyor; değer gösterilmez.
        </p>
      ) : (
        <BazDegeri b={b} />
      )}
      {acik && b !== undefined && (
        <form className="baz-form" onSubmit={(e) => void kaydet(e)} aria-label="Manuel baz değer ölçümü" noValidate>
          <fieldset className="baz-sure">
            <legend>Ölçülen süre</legend>
            <label>
              <span>Dakika</span>
              <input inputMode="numeric" name="dakika" value={dk} onChange={(e) => setDk(e.target.value)} aria-describedby="baz-sure-ipucu" />
            </label>
            <label>
              <span>Saniye</span>
              <input inputMode="numeric" name="saniye" value={sn} onChange={(e) => setSn(e.target.value)} aria-describedby="baz-sure-ipucu" />
            </label>
          </fieldset>
          <p id="baz-sure-ipucu" className="soluk kucuk">
            1 sn – {BAZ_UST_SINIR_S / 3600} saat. Story'nin tüm manuel case'lerini hazırlama süresi.
          </p>
          <label className="baz-not-alani">
            <span>Ölçüm notu (kim, nasıl ölçtü)</span>
            <textarea name="not" rows={2} maxLength={BAZ_NOT_EN_COK} value={not} onChange={(e) => setNot(e.target.value)} />
          </label>
          <label className="satir-ogeler kucuk">
            <input type="checkbox" checked={gercek} onChange={(e) => setGercek(e.target.checked)} />
            <span>Bu değer gerçek bir ölçümden geliyor (tahmin değil).</span>
          </label>
          {dogrulamaHatasi && (
            <p className="hata-metin kucuk" role="alert">
              {dogrulamaHatasi}
            </p>
          )}
          <div className="satir-ogeler">
            <IslemDugmesi roller={["analyst", "po"]} type="submit" calisiyor={islem.calisiyor}>
              Kaydet
            </IslemDugmesi>
            <button type="button" className="dugme dugme-ikincil" onClick={() => setAcik(false)} disabled={islem.calisiyor}>
              Vazgeç
            </button>
          </div>
        </form>
      )}
      {b?.kaynak === "olcum" && yetkili && !acik && (
        <div className="satir-ogeler">
          {silOnayi ? (
            <>
              <span className="kucuk">Ölçüm silinsin mi? Kazanç bu story için artık hesaplanmaz (denetime yazılır).</span>
              <IslemDugmesi roller={["analyst", "po"]} tur="tehlike" kucuk calisiyor={islem.calisiyor} onClick={() => void sil()}>
                Evet, sil
              </IslemDugmesi>
              <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={() => setSilOnayi(false)}>
                Vazgeç
              </button>
            </>
          ) : (
            <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => setSilOnayi(true)}>
              Ölçümü sil
            </button>
          )}
        </div>
      )}
      {islem.hata && <HataKutusu hata={islem.hata} />}
    </Kart>
  );
}
