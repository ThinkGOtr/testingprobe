import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { BugTaslagi, BugTaslakIcerik, MukerrerAday, MukerrerArama } from "../api/types";
import { useBildirim } from "../components/Bildirim";
import { AlanHatasi, BosDurum, Cip, Baglanti, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { KisiAdi } from "../components/KisiAdi";
import { BUG_DURUMU, SEVERITY, type Ton } from "../lib/etiketler";
import { tarih } from "../lib/format";
import { kirmaTaslagiMi } from "../lib/yolHaritasi";

const KAYNAK = { triage: "Triage", consistency: "Tutarlılık denetimi", a11y: "Erişilebilirlik" } as const;

const OLASILIK: Record<NonNullable<MukerrerAday["olasilik"]>, { etiket: string; ton: Ton }> = {
  high: { etiket: "yüksek olasılık", ton: "hata" },
  medium: { etiket: "orta olasılık", ton: "uyari" },
  low: { etiket: "düşük olasılık", ton: "notr" },
};

/**
 * Jira mükerrer aramasının (JQL + dup_rank) durumu. Core `mukerrer_arama` gönderiyorsa o; göndermiyorsa
 * aday varsa "yapıldı", adaysız tutarlılık taslağında "yapılmadı" (boş liste "bulunamadı" değildir).
 */
export function mukerrerAramaDurumu(b: Pick<BugTaslagi, "kaynak" | "mukerrer_adaylari" | "mukerrer_arama">): MukerrerArama["durum"] {
  if (b.mukerrer_arama) return b.mukerrer_arama.durum;
  if (b.mukerrer_adaylari.length > 0) return "yapildi";
  return b.kaynak === "consistency" ? "yapilmadi" : "yapildi";
}

export function mukerrerAramasiYapilmadi(b: Pick<BugTaslagi, "kaynak" | "mukerrer_adaylari" | "mukerrer_arama">): boolean {
  return mukerrerAramaDurumu(b) === "yapilmadi";
}

/** Durum core `bug_draft` makinesinden; "bağlandı" ayrı durum değil, `published` + `karar === "link"`. */
function durum(b: BugTaslagi): { etiket: string; ton: Ton } {
  if (b.durum === "published" && b.jira_silindi) return { etiket: `Silindi: ${b.jira_key}`, ton: "notr" };
  if (b.durum === "published" && b.karar === "link") return { etiket: `Bağlandı: ${b.link_key ?? b.jira_key}`, ton: "bilgi" };
  if (b.durum === "published") return { etiket: `Jira'da açıldı: ${b.jira_key}`, ton: "basari" };
  return BUG_DURUMU[b.durum] ?? { etiket: b.durum, ton: "notr" };
}

function JiraAnahtari({ anahtar, url }: { anahtar: string; url: string | null | undefined }) {
  return url ? (
    <a className="mono" href={url} target="_blank" rel="noreferrer">
      {anahtar}
      <span className="gorunmez"> (Jira'da, yeni sekmede açılır)</span>
    </a>
  ) : (
    <span className="mono">{anahtar}</span>
  );
}

function aramaOzeti(b: BugTaslagi): string {
  const d = mukerrerAramaDurumu(b);
  if (d === "yapilmadi") return "Arama yapılmadı";
  if (d === "suruyor") return "Aranıyor…";
  if (d === "basarisiz") return "Arama başarısız";
  return b.mukerrer_adaylari.map((m) => m.key).join(", ") || "—";
}

export const KIRMA_CIPI = "Kasıtlı kırma koşusu (BREAK_CAMPAIGN)";
const KIRMA_ACIKLAMA = "Bu taslak bilerek bozulmuş (BREAK_CAMPAIGN / kırarak doğrula) koşudan geldi; gerçek hata değildir.";

/**
 * Kasıtlı kırma koşusunun kırmızısından gelen taslakların kimlikleri (taslak → triage hatası → koşu;
 * `break_verify` tetiği ya da `break_campaign`). Yol haritasıyla aynı kural (`kirmaTaslagiMi`).
 * Hata/koşu listesi okunamazsa boş küme: işaret konmaz (yanlış "kasıtlı" denmez).
 */
export function useKirmaTaslaklari(buglar: BugTaslagi[] | null | undefined): Set<string> {
  const anahtar = (buglar ?? [])
    .map((b) => b.failure_id)
    .filter(Boolean)
    .sort()
    .join(",");
  const v = useVeri(async () => {
    if (!anahtar) return { hatalar: [], kosular: [] };
    const [hatalar, kosular] = await Promise.all([api.hatalar().catch(() => []), api.kosular().catch(() => [])]);
    return { hatalar, kosular };
  }, [anahtar]);
  return useMemo(() => {
    const k = new Set<string>();
    if (!v.veri) return k;
    for (const b of buglar ?? []) if (kirmaTaslagiMi(b, v.veri.hatalar, v.veri.kosular)) k.add(b.id);
    return k;
  }, [buglar, v.veri]);
}

function KirmaCipi() {
  return (
    <Cip ton="uyari" title={KIRMA_ACIKLAMA}>
      {KIRMA_CIPI}
    </Cip>
  );
}

export function BugTaslaklari() {
  const v = useVeri(() => api.bugTaslaklari(), []);
  const kirmaIds = useKirmaTaslaklari(v.veri);
  const sessiz = useGeciktirilmis(() => void v.yenile(true));
  useOlay(sessiz, ["bug.published", "bug.updated", "failure.classified", "finding.updated"]);
  return (
    <>
      <SayfaBasligi baslik="Bug taslakları" aciklama="AI taslak hazırlar ve Jira'da olası mükerrerleri bulur; kayıt yalnızca testçi onayıyla açılır ya da bağlanır." />
      <Kart>
        {v.yukleniyor && !v.veri ? (
          <Yukleniyor />
        ) : v.hata && !v.veri ? (
          <HataKutusu hata={v.hata} kaynak={v.hataNesnesi} yenile={() => void v.yenile()} />
        ) : (v.veri ?? []).length === 0 ? (
          <BosDurum baslik="Bug taslağı yok." />
        ) : (
          <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Bug taslakları tablosu">
            <table className="tablo">
              <thead>
                <tr>
                  <th scope="col">Özet</th>
                  <th scope="col">Kaynak</th>
                  <th scope="col">Story</th>
                  <th scope="col">Önem</th>
                  <th scope="col">Mükerrer adayı</th>
                  <th scope="col">Durum</th>
                  <th scope="col">Oluşturma</th>
                </tr>
              </thead>
              <tbody>
                {(v.veri ?? []).map((b) => {
                  const d = durum(b);
                  const yapilmadi = mukerrerAramaDurumu(b) !== "yapildi";
                  return (
                    <tr key={b.id}>
                      <td>
                        <Link to={`/bug-taslaklari/${encodeURIComponent(b.id)}`} className="satir-baglanti">
                          {b.icerik.summary}
                        </Link>{" "}
                        <ReplayRozeti mode={b.mode} degerlendirme={b.degerlendirme} />
                        {b.icerik.uretim === "sablon" && <Cip ton="notr">Şablon</Cip>}
                        {kirmaIds.has(b.id) && (
                          <span data-testid="kirma-cipi">
                            {" "}
                            <KirmaCipi />
                          </span>
                        )}
                      </td>
                      <td>{KAYNAK[b.kaynak]}</td>
                      <td className="mono">{b.icerik.story_key ?? "—"}</td>
                      <td>{SEVERITY[b.icerik.severity_suggestion]}</td>
                      <td className={yapilmadi ? "soluk" : "mono"}>{aramaOzeti(b)}</td>
                      <td>
                        <Cip ton={d.ton}>{d.etiket}</Cip>
                      </td>
                      <td>{tarih(b.olusturma)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Kart>
    </>
  );
}

/** `rules/schemas/bug_draft.schema.json` sınırları (summary maxLength 120; metin alanları minLength 1). */
export const OZET_AZAMI = 120;

const ALAN_ADI: Record<string, string> = {
  summary: "Özet",
  steps: "Adımlar",
  expected: "Beklenen",
  actual: "Gerçekleşen",
  environment: "Ortam",
  severity_suggestion: "Önem önerisi",
  story_key: "Story anahtarı",
  test_case_key: "Test anahtarı",
  evidence: "Kanıt",
  labels: "Etiketler",
};

/** Gönderimden önce şema denetimi (core'un 422'sini beklemeden Türkçe alan mesajı). */
export function icerikHatasi(i: Pick<BugTaslakIcerik, "summary" | "expected" | "actual" | "environment">, steps: string[]): string | null {
  const ozet = i.summary.trim();
  if (!ozet) return "Özet boş olamaz.";
  if (ozet.length > OZET_AZAMI) return `Özet en fazla ${OZET_AZAMI} karakter olabilir (şu an ${ozet.length}).`;
  if (steps.length === 0) return "En az bir adım gerekli.";
  if (!i.expected.trim()) return "Beklenen boş olamaz.";
  if (!i.actual.trim()) return "Gerçekleşen boş olamaz.";
  if (!i.environment.trim()) return "Ortam boş olamaz.";
  return null;
}

/**
 * Core 422 "Bug taslağı şemaya uymuyor — summary: '…' is too long; steps: …" (jsonschema İngilizcesi)
 * → Türkçe alan mesajları. Tanınmayan satır alan adıyla genel bir mesaja döner; İngilizce metin gösterilmez.
 */
export function semaHatasiTurkce(detay: string): string {
  const m = /şemaya uymuyor\s*[—-]\s*(.*)$/s.exec(detay);
  if (!m) return detay;
  const satirlar = m[1].split(/;\s*(?=[a-z_]+(?:\.\w+)*: )/).filter(Boolean);
  const mesajlar = satirlar.map((x) => {
    const e = /^([\w.]+):\s*(.*)$/s.exec(x.trim());
    const yer = e ? e[1] : "";
    const ileti = e ? e[2] : x;
    const kok = yer.split(".")[0];
    const ad = ALAN_ADI[kok] ?? (kok || "İçerik");
    if (/is too long/.test(ileti)) return kok === "summary" ? `${ad} en fazla ${OZET_AZAMI} karakter olabilir` : `${ad} çok uzun`;
    if (/is too short|should be non-empty|non-empty/.test(ileti)) return `${ad} boş olamaz`;
    if (/is a required property/.test(ileti)) return "Zorunlu bir alan eksik";
    if (/is not one of/.test(ileti)) return `${ad} geçerli bir değer değil`;
    if (/does not match|is not valid under any/.test(ileti)) return `${ad} biçimi geçersiz`;
    return `${ad} şemaya uymuyor`;
  });
  return `Taslak kaydedilemedi: ${[...new Set(mesajlar)].join("; ")}.`;
}

function satirlar(s: string): string[] {
  return s
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);
}

function MukerrerKarti({
  b,
  taslak,
  calisiyor,
  bagla,
  aramayiYenile,
}: {
  b: BugTaslagi;
  taslak: boolean;
  calisiyor: boolean;
  bagla: (anahtar: string) => void;
  aramayiYenile: () => void;
}) {
  const a = b.mukerrer_arama;
  const d = mukerrerAramaDurumu(b);
  return (
    <Kart
      baslik={
        <span className="satir-ogeler">
          Olası mükerrerler <ReplayRozeti mode={a?.mode} degerlendirme={a?.degerlendirme} />
        </span>
      }
      eylemler={
        taslak &&
        d !== "suruyor" && (
          <IslemDugmesi roller={["tester"]} tur="ikincil" kucuk calisiyor={calisiyor} onClick={aramayiYenile}>
            {d === "yapildi" ? "Aramayı yenile" : "Mükerrer aramasını başlat"}
          </IslemDugmesi>
        )
      }
    >
      {d === "yapilmadi" ? (
        <BosDurum baslik="Mükerrer araması yapılmadı.">
          Bu taslak için Jira'da benzer açık bug aranmadı{a?.neden ? ` (${a.neden})` : ""}; boş liste "benzer kayıt yok" anlamına gelmez.
        </BosDurum>
      ) : d === "suruyor" ? (
        <Yukleniyor metin="Jira'da benzer açık bug'lar aranıyor…" />
      ) : d === "basarisiz" ? (
        <Uyari ton="hata" baslik="Mükerrer araması başarısız">
          {a?.hata ?? "Jira araması tamamlanamadı."} Onaylamadan önce Jira'yı elle kontrol edin.
        </Uyari>
      ) : b.mukerrer_adaylari.length === 0 ? (
        <BosDurum baslik="Jira'da benzer açık bug bulunamadı." />
      ) : (
        <>
          {(a?.mode === "replay_miss" || a?.ai_onerisi_yok || b.mukerrer_adaylari.every((m) => !m.gerekce && !m.olasilik)) && (
            <Uyari ton="uyari" baslik="Mükerrer sıralaması yapılamadı">
              {a?.mode === "replay_miss" ? "REPLAY-MISS: bu aday kümesi için kayıtlı model sıralaması yok. " : ""}
              Adaylar Jira aramasının sırasıyla, AI gerekçesi olmadan gösteriliyor; karar yine testçinin.
            </Uyari>
          )}
          {a?.oneri ? (
            <p className="kucuk" data-testid="mukerrer-onerisi">
              <strong>AI önerisi:</strong>{" "}
              {a.oneri === "link"
                ? `mevcut kayda bağla (${a.oneri_link_key ?? b.mukerrer_adaylari[0].key})`
                : // "aynı hata değil" yalnızca model gerçekten "new" döndürdüyse (core gerekçesi yoksa) söylenir.
                  a.neden
                  ? "yeni kayıt aç"
                  : "yeni kayıt aç (adaylar aynı hata değil)"}
              <span className="soluk"> · karar testçinin</span>
              {a.neden && <span className="soluk"> · {a.neden}</span>}
            </p>
          ) : a?.ai_onerisi_yok ? (
            <p className="kucuk" data-testid="mukerrer-onerisi">
              <strong>AI önerisi yok</strong> ({a.ai_onerisi_yok})<span className="soluk"> · karar testçinin</span>
            </p>
          ) : null}
          <ul className="mukerrer-liste" aria-label="Mükerrer adayları">
            {b.mukerrer_adaylari.map((m) => {
              const ol = m.olasilik ? OLASILIK[m.olasilik] : null;
              const onerilen = a?.oneri === "link" && (a.oneri_link_key ?? b.mukerrer_adaylari[0].key) === m.key;
              return (
                <li key={m.key} className={onerilen ? "aday-oneri" : undefined}>
                  <div className="satir-ogeler">
                    {m.sira != null && <span className="soluk kucuk">#{m.sira}</span>}
                    <JiraAnahtari anahtar={m.key} url={m.url} />
                    <strong>{m.summary}</strong>
                    {m.durum && <Cip ton="notr">{m.durum}</Cip>}
                    {ol && <Cip ton={ol.ton}>{ol.etiket}</Cip>}
                  </div>
                  {m.gerekce && (
                    <p>
                      <span className="soluk kucuk">AI gerekçesi: </span>
                      {m.gerekce}
                    </p>
                  )}
                  {m.sinyaller.length > 0 && <p className="kucuk soluk">{m.sinyaller.join(" · ")}</p>}
                  {taslak && (
                    <div className="aday-eylemler">
                      <IslemDugmesi roller={["tester"]} tur="ikincil" kucuk calisiyor={calisiyor} onClick={() => bagla(m.key)}>
                        {`${m.key} kaydına bağla`}
                      </IslemDugmesi>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
      {a?.jql && (
        <details className="kucuk">
          <summary>Arama sorgusu (JQL)</summary>
          <pre className="kod-blok" tabIndex={0}>
            {a.jql}
          </pre>
        </details>
      )}
    </Kart>
  );
}

function YayinDurumu({ b }: { b: BugTaslagi }) {
  if (b.yayin_hatasi) {
    return (
      <Uyari ton="hata" baslik="Jira'ya yazılamadı">
        {b.yayin_hatasi}
      </Uyari>
    );
  }
  if (b.durum === "approved" || b.yayin_suruyor) return <Uyari ton="bilgi">Testçi onayladı; kayıt Jira'ya yazılıyor (publish_bug)…</Uyari>;
  if (b.durum === "dismissed")
    return (
      <Uyari ton="basari" baslik="Taslak reddedildi">
        Jira'ya hiçbir şey yazılmadı.{b.ret_gerekcesi && ` Gerekçe: ${b.ret_gerekcesi}`}
      </Uyari>
    );
  if (b.durum !== "published") return null;
  if (b.jira_silindi)
    return (
      <Uyari ton="bilgi" baslik="Jira kaydı silindi">
        <span data-testid="yayin-sonucu">
          {b.jira_key} bu sistemce açılmıştı; demo sıfırlamasında Jira'dan silindi.
        </span>
      </Uyari>
    );
  const anahtar = b.karar === "link" ? (b.link_key ?? b.jira_key) : b.jira_key;
  const baglar = [b.icerik.story_key, b.icerik.test_case_key].filter(Boolean).join(" ve ");
  return (
    <Uyari ton="basari" baslik={b.karar === "link" ? "Mevcut kayda bağlandı" : "Jira'da yeni Bug açıldı"}>
      <span data-testid="yayin-sonucu">
        {anahtar && <JiraAnahtari anahtar={anahtar} url={b.jira_url} />}
        {b.karar === "link" ? " kaydına bağlandı" : " açıldı"}
        {baglar && `; ${baglar} ile ilişkilendirildi`}.
      </span>
    </Uyari>
  );
}

export function BugTaslakDetay() {
  const { id = "" } = useParams();
  const v = useVeri(() => api.bugTaslagi(id), [id]);
  const sessiz = useGeciktirilmis(() => void v.yenile(true));
  useOlay(sessiz, ["bug.published", "bug.updated"], id);
  const [icerik, setIcerik] = useState<BugTaslakIcerik | null>(null);
  const [adimMetni, setAdimMetni] = useState("");
  const [baglanacak, setBaglanacak] = useState("");
  const [uyari, setUyari] = useState<string | null>(null);
  const [retGerekcesi, setRetGerekcesi] = useState("");
  const islem = useIslem();
  const bildir = useBildirim();
  const tekil = useMemo(() => (v.veri ? [v.veri] : []), [v.veri]);
  const kirma = useKirmaTaslaklari(tekil).has(v.veri?.id ?? "");

  useEffect(() => {
    if (v.veri) {
      setIcerik(v.veri.icerik);
      setAdimMetni(v.veri.icerik.steps.join("\n"));
      setBaglanacak(v.veri.mukerrer_arama?.oneri_link_key ?? v.veri.mukerrer_adaylari[0]?.key ?? "");
    }
  }, [v.veri]);

  if (v.yukleniyor && !v.veri) return <Yukleniyor />;
  if (v.hata && !v.veri) return <HataKutusu hata={v.hata} kaynak={v.hataNesnesi} yenile={() => void v.yenile()} />;
  const b = v.veri;
  if (!b || !icerik) return null;
  const taslak = b.durum === "draft";
  const d = durum(b);
  const aramaYok = mukerrerAramaDurumu(b) !== "yapildi";
  // Karar, ekranda görülen taslağın hash'iyle bağlanır (düzenlemeler karar gövdesindedir).
  const bag = { icerik_hash: b.icerik_hash };
  const cakisma = { cakismada: () => void v.yenile(true) };

  async function yeniKayit(e: FormEvent) {
    e.preventDefault();
    if (!icerik) return;
    const steps = satirlar(adimMetni);
    const sorun = icerikHatasi(icerik, steps);
    if (sorun) return setUyari(sorun);
    setUyari(null);
    const s = await islem.calistir(
      () => api.bugKarari(b!.id, { ...bag, karar: "new", icerik: { ...icerik, summary: icerik.summary.trim(), steps } }),
      cakisma,
    );
    if (s) {
      v.setVeri(s);
      bildir(s.jira_key ? `Jira'da ${s.jira_key} açıldı.` : "Onaylandı; kayıt Jira'ya yazılıyor.");
    }
  }

  async function bagla(anahtarHam: string) {
    const anahtar = anahtarHam.trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9]+-\d+$/.test(anahtar)) return setUyari("Geçerli bir Jira anahtarı girin (ör. TPD-21).");
    setUyari(null);
    const s = await islem.calistir(() => api.bugKarari(b!.id, { ...bag, karar: "link", link_key: anahtar }), cakisma);
    if (s) {
      v.setVeri(s);
      bildir(`Taslak ${s.link_key ?? s.jira_key ?? anahtar} kaydına bağlandı.`);
    }
  }

  async function reddet() {
    const gerekce = retGerekcesi.trim();
    if (!gerekce) return setUyari("Reddetmek için gerekçe yazın.");
    setUyari(null);
    const s = await islem.calistir(() => api.bugKarari(b!.id, { ...bag, karar: "dismiss", gerekce }), cakisma);
    if (s) {
      v.setVeri(s);
      setRetGerekcesi("");
      bildir("Taslak reddedildi; Jira'ya yazılmadı.");
    }
  }

  /** Düzenlemeyi kaydet (onay değil; içerik hash'i yenilenir). */
  async function kaydet() {
    if (!icerik) return;
    const steps = satirlar(adimMetni);
    const sorun = icerikHatasi(icerik, steps);
    if (sorun) return setUyari(sorun);
    setUyari(null);
    const s = await islem.calistir(
      () => api.bugKarari(b!.id, { ...bag, karar: "edit", icerik: { ...icerik, summary: icerik.summary.trim(), steps } }),
      cakisma,
    );
    if (s) {
      v.setVeri(s);
      bildir("Taslak kaydedildi (henüz onaylanmadı).");
    }
  }

  async function taslagaAl() {
    const s = await islem.calistir(() => api.bugKarari(b!.id, { ...bag, karar: "reopen" }), cakisma);
    if (s) {
      v.setVeri(s);
      bildir("Taslak yeniden karar bekliyor.");
    }
  }

  async function aramayiYenile() {
    const s = await islem.calistir(() => api.bugHazirla(b!.id));
    if (s) {
      bildir(s.mesaj ?? "Mükerrer araması başladı.");
      void v.yenile(true);
    }
  }

  async function yayiniYinele() {
    const s = await islem.calistir(() => api.bugYayiniYinele(b!.id), cakisma);
    if (s) {
      v.setVeri(s);
      bildir(s.jira_key ? `Jira: ${s.jira_key}` : "Yayın yeniden kuyruğa alındı.");
    }
  }

  const duzenlendi =
    taslak &&
    (icerik.summary !== b.icerik.summary ||
      icerik.expected !== b.icerik.expected ||
      icerik.actual !== b.icerik.actual ||
      icerik.environment !== b.icerik.environment ||
      icerik.severity_suggestion !== b.icerik.severity_suggestion ||
      satirlar(adimMetni).join("\n") !== b.icerik.steps.join("\n"));

  const alan = <K extends keyof BugTaslakIcerik>(k: K, deger: BugTaslakIcerik[K]) => setIcerik({ ...icerik, [k]: deger });
  const storyUrl = b.jira_browse_url && icerik.story_key ? `${b.jira_browse_url.replace(/\/+$/, "")}/${encodeURIComponent(icerik.story_key)}` : null;
  const testUrl = b.jira_browse_url && icerik.test_case_key ? `${b.jira_browse_url.replace(/\/+$/, "")}/${encodeURIComponent(icerik.test_case_key)}` : null;

  return (
    <>
      <SayfaBasligi
        ust={<Link to="/bug-taslaklari">← Bug taslakları</Link>}
        baslik={b.icerik.summary}
        aciklama={
          <span className="satir-ogeler">
            <Cip ton={d.ton}>{d.etiket}</Cip>
            <span>{KAYNAK[b.kaynak]}</span>
            <ReplayRozeti mode={b.mode} degerlendirme={b.degerlendirme} />
            {b.icerik.uretim === "sablon" && (
              <Cip ton="notr" title="Doğrulanmış kanıttan şablonla yazıldı; model çağrısı yok">Şablon</Cip>
            )}
            {kirma && <KirmaCipi />}
            {b.failure_id && <Link to={`/hatalar/${encodeURIComponent(b.failure_id)}`}>Triage sonucu</Link>}
            {b.onaylayan && (
              <span className="soluk">
                <KisiAdi ad={b.onaylayan} />
                {b.onay_zamani && ` · ${tarih(b.onay_zamani)}`}
              </span>
            )}
          </span>
        }
      />

      {kirma && (
        <div data-testid="kirma-uyarisi">
          <Uyari baslik={KIRMA_CIPI}>
            {KIRMA_ACIKLAMA}{" "}
            {taslak
              ? "Önerilen karar: gerekçeyle reddedin (Jira'ya hiçbir şey yazılmaz). \"Onayla ve Jira'da aç\" sahte bir Bug açar; AI önerisi bu bilgiyi bilmez."
              : "Demo sırasında bu taslağa dokunulmaz."}
          </Uyari>
        </div>
      )}
      <YayinDurumu b={b} />
      {b.yayin_hatasi && b.durum !== "published" && (
        <p>
          <IslemDugmesi roller={["tester"]} tur="ikincil" calisiyor={islem.calisiyor} onClick={() => void yayiniYinele()}>
            Yayını yeniden dene
          </IslemDugmesi>
        </p>
      )}
      {b.durum === "dismissed" && (
        <p>
          <IslemDugmesi roller={["tester"]} tur="ikincil" calisiyor={islem.calisiyor} onClick={() => void taslagaAl()}>
            Taslağa al
          </IslemDugmesi>
        </p>
      )}

      <MukerrerKarti
        b={b}
        taslak={taslak}
        calisiyor={islem.calisiyor}
        bagla={(k) => void bagla(k)}
        aramayiYenile={() => void aramayiYenile()}
      />

      <Kart baslik={taslak ? "Taslak (düzenlenebilir)" : "Kayıt"}>
        <form onSubmit={yeniKayit} className="form" noValidate>
          <fieldset disabled={!taslak} className="duz-fieldset">
            <div className="alan">
              <label htmlFor="bug-ozet">Özet</label>
              <input
                id="bug-ozet"
                value={icerik.summary}
                maxLength={OZET_AZAMI}
                aria-describedby="bug-ozet-sayac"
                onChange={(e) => alan("summary", e.target.value)}
              />
              <span id="bug-ozet-sayac" className={`kucuk ${icerik.summary.length > OZET_AZAMI ? "hata-metin" : "soluk"}`} data-testid="ozet-sayac">
                {icerik.summary.length}/{OZET_AZAMI} karakter
              </span>
            </div>
            <div className="alan">
              <label htmlFor="bug-adimlar">Adımlar (her satır bir adım)</label>
              <textarea id="bug-adimlar" rows={4} value={adimMetni} onChange={(e) => setAdimMetni(e.target.value)} />
            </div>
            <div className="iki-sutun">
              <div className="alan">
                <label htmlFor="bug-beklenen">Beklenen</label>
                <textarea id="bug-beklenen" rows={2} value={icerik.expected} onChange={(e) => alan("expected", e.target.value)} />
              </div>
              <div className="alan">
                <label htmlFor="bug-gerceklesen">Gerçekleşen</label>
                <textarea id="bug-gerceklesen" rows={2} value={icerik.actual} onChange={(e) => alan("actual", e.target.value)} />
              </div>
            </div>
            <div className="iki-sutun">
              <div className="alan">
                <label htmlFor="bug-ortam">Ortam</label>
                <input id="bug-ortam" value={icerik.environment} onChange={(e) => alan("environment", e.target.value)} />
              </div>
              <div className="alan">
                <label htmlFor="bug-onem">Önem önerisi</label>
                <select
                  id="bug-onem"
                  value={icerik.severity_suggestion}
                  onChange={(e) => alan("severity_suggestion", e.target.value as BugTaslakIcerik["severity_suggestion"])}
                >
                  {Object.entries(SEVERITY).map(([k, etiket]) => (
                    <option key={k} value={k}>
                      {etiket}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </fieldset>
          <p className="kucuk">
            Story {icerik.story_key ? <JiraAnahtari anahtar={icerik.story_key} url={storyUrl} /> : "—"} · Test{" "}
            {icerik.test_case_key ? <JiraAnahtari anahtar={icerik.test_case_key} url={testUrl} /> : "—"} · Etiketler{" "}
            <span className="mono">{icerik.labels.join(", ")}</span>
          </p>
          {icerik.evidence.length > 0 && (
            <section aria-label="Kanıt bağlantıları">
              <h3 className="kanit-baslik">Kanıt</h3>
              <ul className="duz-liste">
                {icerik.evidence.map((e) => (
                  <li key={`${e.tur}-${e.etiket}`}>
                    <Baglanti href={e.url} yokNedeni={e.url?.startsWith("#") ? undefined : "bağlantı yok"}>
                      {e.etiket}
                    </Baglanti>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {duzenlendi && (
            <p className="satir-ogeler">
              <IslemDugmesi roller={["tester"]} tur="ikincil" kucuk calisiyor={islem.calisiyor} onClick={() => void kaydet()}>
                Değişiklikleri kaydet
              </IslemDugmesi>
              <span className="kucuk soluk">Kaydetmek onay değildir; Jira'ya yazmak için aşağıdan karar verin.</span>
            </p>
          )}
          {taslak && aramaYok && (
            <Uyari baslik="Onaylamadan önce Jira'yı kontrol edin">
              Bu taslak için mükerrer araması tamamlanmadı. Aynı hata Jira'da açık olabilir; önce benzer açık bug'ları
              arayın, varsa "Mevcut kayda bağla" ile bağlayın. Demo sunumunda bu taslağı "Onayla ve Jira'da aç" ile
              onaylamayın (mükerrer kayıt açılır).
            </Uyari>
          )}
          {taslak && (
            <div className="karar-paneli karar-paneli-uclu">
              <div>
                <h3>Yeni kayıt</h3>
                <p className="soluk kucuk">Düzenlenmiş taslak onaylanan içerik hash'iyle Jira'ya Bug olarak yazılır; story ve teste bağlanır.</p>
                <IslemDugmesi
                  roller={["tester"]}
                  type="submit"
                  tur={kirma ? "ikincil" : "birincil"}
                  calisiyor={islem.calisiyor}
                  title={kirma ? "Kasıtlı kırma koşusu: gerçek hata değil; önerilen karar Reddet" : undefined}
                >
                  Onayla ve Jira'da aç
                </IslemDugmesi>
              </div>
              <div>
                <h3>Mevcut kayda bağla</h3>
                <div className="alan alan-satir">
                  <label htmlFor="bug-bagla">Jira anahtarı</label>
                  <input
                    id="bug-bagla"
                    className="mono"
                    value={baglanacak}
                    onChange={(e) => setBaglanacak(e.target.value)}
                    list="mukerrer-anahtarlar"
                    placeholder="TPD-21"
                  />
                  <datalist id="mukerrer-anahtarlar">
                    {b.mukerrer_adaylari.map((m) => (
                      <option key={m.key} value={m.key} />
                    ))}
                  </datalist>
                </div>
                <IslemDugmesi roller={["tester"]} tur="ikincil" calisiyor={islem.calisiyor} onClick={() => void bagla(baglanacak)}>
                  Mevcut kayda bağla
                </IslemDugmesi>
              </div>
              <div>
                <h3>
                  Kayıt açma{" "}
                  {kirma && (
                    <Cip ton="uyari" title={KIRMA_ACIKLAMA}>
                      Önerilen
                    </Cip>
                  )}
                </h3>
                <p className="soluk kucuk">Taslak hata değilse gerekçeyle reddedin; Jira'ya hiçbir şey yazılmaz.</p>
                <div className="alan">
                  <label htmlFor="bug-ret">Ret gerekçesi</label>
                  <textarea
                    id="bug-ret"
                    rows={2}
                    value={retGerekcesi}
                    placeholder={kirma ? "ör. Kasıtlı kırma (BREAK_CAMPAIGN) koşusu; gerçek hata değil." : undefined}
                    onChange={(e) => setRetGerekcesi(e.target.value)}
                  />
                </div>
                <IslemDugmesi
                  roller={["tester"]}
                  tur="tehlike"
                  calisiyor={islem.calisiyor}
                  disabled={!retGerekcesi.trim()}
                  title={retGerekcesi.trim() ? undefined : "Önce gerekçe yazın"}
                  onClick={reddet}
                >
                  Taslağı reddet
                </IslemDugmesi>
              </div>
            </div>
          )}
          {(uyari || islem.hata) && (
            <AlanHatasi asistan={!uyari && islem.hata ? { hata: semaHatasiTurkce(islem.hata), kaynak: islem.hataNesnesi } : null}>
              {uyari ?? (islem.hata ? semaHatasiTurkce(islem.hata) : null)}
            </AlanHatasi>
          )}
          {!taslak && <p className="kucuk soluk">Bu taslak için karar verildi; içerik artık değiştirilemez.</p>}
        </form>
      </Kart>
    </>
  );
}
