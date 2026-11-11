import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { YayinOnizlemeKalemi, YayinSonucu } from "../api/types";
import { jiraKayitAdresi } from "../api/uyum";
import { useOturum } from "../auth";
import { useBildirim } from "../components/Bildirim";
import { Baglanti, BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import type { Ton } from "../lib/etiketler";

const ISLEM: Record<YayinOnizlemeKalemi["islem"], { etiket: string; ton: Ton }> = {
  create: { etiket: "Oluşturulacak", ton: "basari" },
  skip_existing: { etiket: "Zaten yayında", ton: "notr" },
  blocked_hash_mismatch: { etiket: "Engelli: onaydan sonra değişmiş", ton: "hata" },
  blocked_not_approved: { etiket: "Engelli: onaylı değil", ton: "uyari" },
  blocked_no_story: { etiket: "Engelli: Jira story'si yok", ton: "uyari" },
  blocked_requirement_changed: { etiket: "Engelli: story değişti, PO onayı yenilenmeli", ton: "hata" },
  blocked_not_ready: { etiket: "Engelli: hazır değil", ton: "uyari" },
  blocked_gate: { etiket: "Engelli: denetim kapısı", ton: "uyari" },
};

/** Core neden metni göndermediyse gösterilen açıklama (011 §4.7: yalnız hazır case yayınlanır). */
const HAZIR_DEGIL_NEDENI =
  "Case hazır değil (varsayıma bağlı ya da engelli). Case review ekranında \"Düzelt\" ile hazır yapın ya da reddedin.";

const HEDEF = { jira: "Jira (Test issue)", xray: "Xray Cloud" } as const;

/** Yayın sonucunun özeti: oluşturulan / zaten var / başarısız; ikisi birden varsa kısmi başarı. */
export function yayinOzeti(s: YayinSonucu) {
  const olusan = s.sonuclar.filter((x) => x.durum === "created").length;
  const vardi = s.sonuclar.filter((x) => x.durum === "exists").length;
  const basarisiz = s.sonuclar.filter((x) => x.durum === "failed").length;
  return { olusan, vardi, basarisiz, kismi: basarisiz > 0 && olusan + vardi > 0 };
}

/** Yayın önizleme ve yayın analist rolüne açıktır (core `GET /publish/preview` → 403). */
export const YAYIN_ROLU_GEREKLI = "Yayın analist rolü gerektirir";

export function Yayin() {
  const { kullanici } = useOturum();
  if (kullanici && kullanici.rol !== "analyst") return <YayinYetkisiz />;
  return <YayinEkrani />;
}

function YayinYetkisiz() {
  const { id = "" } = useParams();
  return (
    <>
      <SayfaBasligi
        ust={<Link to={`/gereksinimler/${encodeURIComponent(id)}/caseler`}>← Case review</Link>}
        baslik="Yayın önizleme"
      />
      <Uyari ton="bilgi" baslik={YAYIN_ROLU_GEREKLI}>
        Case'lerin test yönetimine yayını ve önizlemesi analist rolüyle yapılır. Case'lerin durumunu Case review ekranında
        görebilirsiniz.
      </Uyari>
    </>
  );
}

function YayinEkrani() {
  const { id = "" } = useParams();
  const onizleme = useVeri(() => api.yayinOnizleme(id), [id]);
  const gereksinim = useVeri(() => api.gereksinim(id), [id]);
  // Kapsam denetimi (core case-metrics `kapsanmayan_ac`): yayında test edilmeyen AC kalmasın.
  const metrik = useVeri(() => api.caseMetrikleri(id).catch(() => null), [id]);
  const [secili, setSecili] = useState<Set<string>>(new Set());
  const [sonuc, setSonuc] = useState<YayinSonucu | null>(null);
  /** POST /publish arka plan işi döndürdüyse: sonuç `publish.*` olaylarıyla gelir. */
  const [bekleyenIs, setBekleyenIs] = useState<string | null>(null);
  const islem = useIslem();
  const bildir = useBildirim();
  const sessiz = useGeciktirilmis(() => {
    void onizleme.yenile(true);
    void metrik.yenile(true);
  });
  useOlay(
    (o) => {
      if (typeof o.data.requirement_id === "string" && o.data.requirement_id !== id) return;
      sessiz();
      if (/^publish\.(completed|done|failed)$/.test(o.type)) setBekleyenIs(null);
    },
    ["publish.updated", "case.updated"],
  );

  const kalemler = onizleme.veri?.kalemler ?? [];
  const olusturulabilir = kalemler.filter((k) => k.islem === "create");

  useEffect(() => {
    setSecili(new Set(olusturulabilir.map((k) => k.case_id)));
  }, [onizleme.veri]);

  const degistir = (cid: string) =>
    setSecili((s) => {
      const y = new Set(s);
      if (y.has(cid)) y.delete(cid);
      else y.add(cid);
      return y;
    });

  async function yayinla() {
    const s = await islem.calistir(() => api.yayinla([...secili]));
    if (!s) return;
    if (s.sonuclar.length === 0 && s.job_id) {
      setBekleyenIs(s.job_id);
      bildir("Yayın başlatıldı; sonuçlar geldikçe tablo güncellenir.");
    } else {
      setSonuc(s);
      const oz = yayinOzeti(s);
      bildir(
        oz.basarisiz
          ? `${oz.olusan} test yayınlandı, ${oz.basarisiz} başarısız.`
          : `${oz.olusan} test ${HEDEF[s.hedef]} hedefine yayınlandı.`,
        oz.basarisiz ? "hata" : undefined,
      );
    }
    void onizleme.yenile(true);
  }

  const o = onizleme.veri;
  const kapsanmayan = metrik.veri?.kapsanmayan_ac ?? [];
  const adres = (anahtar: string | null, url?: string | null) =>
    jiraKayitAdresi(anahtar, { url, browseKoku: o?.jira_browse_url, storyAdresi: gereksinim.veri?.jira_url });

  return (
    <>
      <SayfaBasligi
        ust={<Link to={`/gereksinimler/${encodeURIComponent(id)}/caseler`}>← Case review</Link>}
        baslik="Yayın önizleme"
        aciklama="Önizleme: bu ekranda hiçbir kayıt oluşturulmaz. Yalnızca onaylı ve onaydan sonra değişmemiş case'ler yayınlanır; yayın tekrarlansa da aynı içerik ikinci kez oluşturulmaz."
      />
      {onizleme.yukleniyor && !o ? (
        <Yukleniyor />
      ) : onizleme.hata && !o && onizleme.hataKodu === 403 ? (
        <Uyari ton="bilgi" baslik={YAYIN_ROLU_GEREKLI}>
          {onizleme.hata}
        </Uyari>
      ) : onizleme.hata && !o ? (
        <HataKutusu hata={onizleme.hata} kaynak={onizleme.hataNesnesi} yenile={() => void onizleme.yenile()} />
      ) : o ? (
        <>
          <Kart
            baslik="Hedef"
            eylemler={
              <IslemDugmesi
                roller={["analyst"]}
                disabled={secili.size === 0 || bekleyenIs !== null}
                calisiyor={islem.calisiyor || bekleyenIs !== null}
                onClick={yayinla}
              >
                Seçilenleri yayınla ({secili.size})
              </IslemDugmesi>
            }
          >
            <p data-testid="yayin-hedefi">
              <strong>{HEDEF[o.hedef]}</strong> · proje <span className="mono">{o.proje || "—"}</span>
              {o.jira_browse_url && (
                <>
                  {" "}
                  · <span className="mono kucuk">{o.jira_browse_url}</span>
                </>
              )}
              <span className="soluk"> · hedef sunucu yapılandırmasından gelir (TP_TEST_MGMT)</span>
            </p>
            {o.uyarilar.map((u) => (
              <Uyari key={u}>{u}</Uyari>
            ))}
            {kapsanmayan.length > 0 && (
              <div data-testid="yayin-kapsam-uyarisi">
                <Uyari baslik="Kapsanmayan kabul kriteri">
                  Hiçbir güncel case şu kabul kriterlerine atıf yapmıyor: <strong className="mono">{kapsanmayan.join(", ")}</strong>.
                  Yayınlanırsa bu kriterler test edilmemiş kalır. Case review ekranında kapsamı tamamlayın ya da bilinçli olarak devam
                  edin.
                </Uyari>
              </div>
            )}
            {bekleyenIs && (
              <p role="status" className="soluk">
                Yayın işi sürüyor (<span className="mono">{bekleyenIs}</span>)…
              </p>
            )}
            {islem.hata && <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />}
          </Kart>

          {sonuc && <YayinSonucKarti sonuc={sonuc} adres={adres} />}

          <Kart baslik="Oluşturulacak kayıtlar">
            {kalemler.length === 0 ? (
              <BosDurum baslik="Yayınlanacak case yok." />
            ) : (
              <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Oluşturulacak kayıtlar tablosu">
                <table className="tablo">
                  <thead>
                    <tr>
                      <th scope="col">
                        <span className="gorunmez">Seç</span>
                      </th>
                      <th scope="col">Özet</th>
                      <th scope="col">Tür</th>
                      <th scope="col">Bağlantı</th>
                      <th scope="col">Etiketler</th>
                      <th scope="col" className="sayi">
                        Adım
                      </th>
                      <th scope="col">İşlem</th>
                    </tr>
                  </thead>
                  <tbody>
                    {kalemler.map((k) => {
                      const i = ISLEM[k.islem];
                      return (
                        <tr key={k.case_id}>
                          <td>
                            <input
                              type="checkbox"
                              aria-label={`${k.title} yayınla`}
                              checked={secili.has(k.case_id)}
                              disabled={k.islem !== "create"}
                              onChange={() => degistir(k.case_id)}
                            />
                          </td>
                          <td>{k.summary}</td>
                          <td>{k.issue_type}</td>
                          <td className="kucuk">
                            {k.link.story_key ? (
                              <>
                                {k.link.type} <span className="mono">{k.link.story_key}</span>
                              </>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td className="kucuk mono">{k.labels.join(", ")}</td>
                          <td className="sayi">{k.adim_sayisi}</td>
                          <td>
                            <Cip ton={i.ton}>{i.etiket}</Cip>
                            {(k.neden || k.islem === "blocked_not_ready") && (
                              <span className="yayin-neden soluk kucuk" data-testid="yayin-engel-nedeni">
                                {k.neden ?? HAZIR_DEGIL_NEDENI}
                              </span>
                            )}
                            {k.external_key && (
                              <>
                                {" "}
                                <Baglanti href={adres(k.external_key)}>
                                  <span className="mono">{k.external_key}</span>
                                </Baglanti>
                              </>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Kart>
        </>
      ) : null}
    </>
  );
}

function YayinSonucKarti({
  sonuc,
  adres,
}: {
  sonuc: YayinSonucu;
  adres: (anahtar: string | null, url?: string | null) => string | null;
}) {
  const oz = yayinOzeti(sonuc);
  return (
    <Kart baslik="Yayın sonucu">
      <p className="satir-ogeler" data-testid="yayin-ozeti">
        <Cip ton="basari">{oz.olusan} oluşturuldu</Cip>
        <Cip ton="notr">{oz.vardi} zaten vardı</Cip>
        <Cip ton={oz.basarisiz ? "hata" : "notr"}>{oz.basarisiz} başarısız</Cip>
        <span className="soluk">{HEDEF[sonuc.hedef]}</span>
      </p>
      {oz.kismi && (
        <Uyari baslik="Kısmi başarı">
          Bazı case'ler yayınlandı, bazıları yayınlanamadı. Yayınlananlar yeniden denemede tekrar oluşturulmaz; başarısızları
          düzeltip yeniden yayınlayabilirsiniz.
        </Uyari>
      )}
      <ul className="duz-liste">
        {sonuc.sonuclar.map((s) => (
          <li key={s.case_id}>
            <Cip ton={s.durum === "created" ? "basari" : s.durum === "exists" ? "notr" : "hata"}>
              {s.durum === "created" ? "Oluşturuldu" : s.durum === "exists" ? "Zaten vardı" : "Başarısız"}
            </Cip>{" "}
            {s.external_key ? (
              <Baglanti href={adres(s.external_key, s.url)}>
                <span className="mono">{s.external_key}</span>
              </Baglanti>
            ) : (
              <span className="mono">{s.case_id}</span>
            )}
            {s.hata && <span className="soluk"> · {s.hata}</span>}
          </li>
        ))}
      </ul>
    </Kart>
  );
}
