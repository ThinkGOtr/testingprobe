import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import type { BugTaslagi, BugTaslakIcerik } from "../api/types";
import { useBildirim } from "../components/Bildirim";
import { BosDurum, Cip, Baglanti, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { BUG_DURUMU, SEVERITY, type Ton } from "../lib/etiketler";
import { tarih } from "../lib/format";

const KAYNAK = { triage: "Triage", consistency: "Tutarlılık denetimi", a11y: "Erişilebilirlik" } as const;

/**
 * Tutarlılık denetiminden doğan taslaklarda core henüz Jira mükerrer araması yapmıyor (§8.12 JQL +
 * dup_rank Faz 4'te). Boş liste "bulunamadı" değil "arama yapılmadı" demektir; ekran bunu iddia etmez.
 */
export function mukerrerAramasiYapilmadi(b: Pick<BugTaslagi, "kaynak" | "mukerrer_adaylari">): boolean {
  return b.kaynak === "consistency" && b.mukerrer_adaylari.length === 0;
}

/** Durum core `bug_draft` makinesinden; "bağlandı" ayrı durum değil, `published` + `karar === "link"`. */
function durum(b: BugTaslagi): { etiket: string; ton: Ton } {
  if (b.durum === "published" && b.karar === "link") return { etiket: `Bağlandı: ${b.link_key ?? b.jira_key}`, ton: "bilgi" };
  if (b.durum === "published") return { etiket: `Jira'da açıldı: ${b.jira_key}`, ton: "basari" };
  return BUG_DURUMU[b.durum] ?? { etiket: b.durum, ton: "notr" };
}

export function BugTaslaklari() {
  const v = useVeri(() => api.bugTaslaklari(), []);
  const sessiz = useGeciktirilmis(() => void v.yenile(true));
  useOlay(sessiz, ["bug.published", "failure.classified", "finding.updated"]);
  return (
    <>
      <SayfaBasligi baslik="Bug taslakları" aciklama="AI taslak hazırlar ve olası mükerrerleri bulur; kayıt yalnızca testçi onayıyla açılır." />
      <Kart>
        {v.yukleniyor && !v.veri ? (
          <Yukleniyor />
        ) : v.hata && !v.veri ? (
          <HataKutusu hata={v.hata} yenile={() => void v.yenile()} />
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
                  return (
                    <tr key={b.id}>
                      <td>
                        <Link to={`/bug-taslaklari/${encodeURIComponent(b.id)}`} className="satir-baglanti">
                          {b.icerik.summary}
                        </Link>{" "}
                        <ReplayRozeti mode={b.mode} />
                        {b.icerik.uretim === "sablon" && <Cip ton="notr">Şablon</Cip>}
                      </td>
                      <td>{KAYNAK[b.kaynak]}</td>
                      <td className="mono">{b.icerik.story_key ?? "—"}</td>
                      <td>{SEVERITY[b.icerik.severity_suggestion]}</td>
                      <td className={mukerrerAramasiYapilmadi(b) ? "soluk" : "mono"}>
                        {mukerrerAramasiYapilmadi(b) ? "Arama yapılmadı" : b.mukerrer_adaylari.map((m) => m.key).join(", ") || "—"}
                      </td>
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

function satirlar(s: string): string[] {
  return s
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);
}

export function BugTaslakDetay() {
  const { id = "" } = useParams();
  const v = useVeri(() => api.bugTaslagi(id), [id]);
  const [icerik, setIcerik] = useState<BugTaslakIcerik | null>(null);
  const [adimMetni, setAdimMetni] = useState("");
  const [baglanacak, setBaglanacak] = useState("");
  const [uyari, setUyari] = useState<string | null>(null);
  const islem = useIslem();
  const bildir = useBildirim();

  useEffect(() => {
    if (v.veri) {
      setIcerik(v.veri.icerik);
      setAdimMetni(v.veri.icerik.steps.join("\n"));
      setBaglanacak(v.veri.mukerrer_adaylari[0]?.key ?? "");
    }
  }, [v.veri]);

  if (v.yukleniyor && !v.veri) return <Yukleniyor />;
  if (v.hata && !v.veri) return <HataKutusu hata={v.hata} yenile={() => void v.yenile()} />;
  const b = v.veri;
  if (!b || !icerik) return null;
  const taslak = b.durum === "draft";
  const d = durum(b);
  // Karar, ekranda görülen taslağın hash'iyle bağlanır (düzenlemeler karar gövdesindedir).
  const bag = { icerik_hash: b.icerik_hash };
  const cakisma = { cakismada: () => void v.yenile(true) };

  async function yeniKayit(e: FormEvent) {
    e.preventDefault();
    if (!icerik) return;
    const steps = satirlar(adimMetni);
    if (!icerik.summary.trim()) return setUyari("Özet boş olamaz.");
    if (steps.length === 0) return setUyari("En az bir adım gerekli.");
    setUyari(null);
    const s = await islem.calistir(
      () => api.bugKarari(b!.id, { ...bag, karar: "new", icerik: { ...icerik, summary: icerik.summary.trim(), steps } }),
      cakisma,
    );
    if (s) {
      v.setVeri(s);
      bildir(`Jira'da ${s.jira_key} açıldı.`);
    }
  }

  async function bagla() {
    const anahtar = baglanacak.trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9]+-\d+$/.test(anahtar)) return setUyari("Geçerli bir Jira anahtarı girin (ör. TPD-21).");
    setUyari(null);
    const s = await islem.calistir(() => api.bugKarari(b!.id, { ...bag, karar: "link", link_key: anahtar }), cakisma);
    if (s) {
      v.setVeri(s);
      bildir(`Taslak ${s.link_key ?? s.jira_key} kaydına bağlandı.`);
    }
  }

  async function reddet() {
    setUyari(null);
    const s = await islem.calistir(() => api.bugKarari(b!.id, { ...bag, karar: "dismiss" }), cakisma);
    if (s) {
      v.setVeri(s);
      bildir("Taslak reddedildi; Jira'ya yazılmadı.");
    }
  }

  const alan = <K extends keyof BugTaslakIcerik>(k: K, deger: BugTaslakIcerik[K]) => setIcerik({ ...icerik, [k]: deger });

  return (
    <>
      <SayfaBasligi
        ust={<Link to="/bug-taslaklari">← Bug taslakları</Link>}
        baslik={b.icerik.summary}
        aciklama={
          <span className="satir-ogeler">
            <Cip ton={d.ton}>{d.etiket}</Cip>
            <span>{KAYNAK[b.kaynak]}</span>
            <ReplayRozeti mode={b.mode} />
            {b.icerik.uretim === "sablon" && (
              <Cip ton="notr" title="Doğrulanmış kanıttan şablonla yazıldı; model çağrısı yok">Şablon</Cip>
            )}
            {b.failure_id && <Link to={`/hatalar/${encodeURIComponent(b.failure_id)}`}>Triage sonucu</Link>}
            {b.onaylayan && (
              <span className="soluk">
                {b.onaylayan} · {tarih(b.onay_zamani)}
              </span>
            )}
          </span>
        }
      />

      <Kart baslik="Olası mükerrerler">
        {mukerrerAramasiYapilmadi(b) ? (
          <BosDurum baslik="Mükerrer araması yapılmadı (Faz 4).">
            Tutarlılık denetiminden gelen taslaklar için Jira'da benzer açık bug henüz aranmıyor; boş liste
            "benzer kayıt yok" anlamına gelmez.
          </BosDurum>
        ) : b.mukerrer_adaylari.length === 0 ? (
          <BosDurum baslik="Jira'da benzer açık bug bulunamadı." />
        ) : (
          <ul className="mukerrer-liste">
            {b.mukerrer_adaylari.map((m) => (
              <li key={m.key}>
                <div className="satir-ogeler">
                  <span className="mono">{m.key}</span>
                  <strong>{m.summary}</strong>
                  <Cip ton="notr">{m.durum}</Cip>
                </div>
                <p>{m.gerekce}</p>
                {m.sinyaller.length > 0 && <p className="kucuk soluk">{m.sinyaller.join(" · ")}</p>}
              </li>
            ))}
          </ul>
        )}
      </Kart>

      <Kart baslik={taslak ? "Taslak (düzenlenebilir)" : "Kayıt"}>
        <form onSubmit={yeniKayit} className="form" noValidate>
          <fieldset disabled={!taslak} className="duz-fieldset">
            <div className="alan">
              <label htmlFor="bug-ozet">Özet</label>
              <input id="bug-ozet" value={icerik.summary} onChange={(e) => alan("summary", e.target.value)} />
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
            Story <span className="mono">{icerik.story_key ?? "—"}</span> · Test <span className="mono">{icerik.test_case_key ?? "—"}</span> · Etiketler{" "}
            <span className="mono">{icerik.labels.join(", ")}</span>
          </p>
          {icerik.evidence.length > 0 && (
            <ul className="duz-liste">
              {icerik.evidence.map((e) => (
                <li key={`${e.tur}-${e.etiket}`}>
                  <Baglanti href={e.url} yokNedeni={e.url?.startsWith("#") ? undefined : "bağlantı yok"}>
                    {e.etiket}
                  </Baglanti>
                </li>
              ))}
            </ul>
          )}

          {taslak && mukerrerAramasiYapilmadi(b) && (
            <Uyari baslik="Onaylamadan önce Jira'yı kontrol edin">
              Bu taslak için mükerrer araması yapılmadı. Aynı hata Jira'da açık olabilir; önce benzer açık bug'ları
              arayın, varsa "Mevcut kayda bağla" ile bağlayın. Demo sunumunda bu taslağı "Onayla ve Jira'da aç" ile
              onaylamayın (mükerrer kayıt açılır).
            </Uyari>
          )}
          {taslak && (
            <div className="karar-paneli">
              <div>
                <h3>Yeni kayıt</h3>
                <p className="soluk kucuk">Düzenlenmiş taslak onaylanan içerik hash'iyle Jira'ya Bug olarak yazılır; story ve teste bağlanır.</p>
                <IslemDugmesi roller={["tester"]} type="submit" calisiyor={islem.calisiyor}>
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
                <IslemDugmesi roller={["tester"]} tur="ikincil" calisiyor={islem.calisiyor} onClick={bagla}>
                  Mevcut kayda bağla
                </IslemDugmesi>
              </div>
              <div>
                <h3>Kayıt açma</h3>
                <p className="soluk kucuk">Taslak hata değilse reddedin; Jira'ya hiçbir şey yazılmaz.</p>
                <IslemDugmesi roller={["tester"]} tur="tehlike" calisiyor={islem.calisiyor} onClick={reddet}>
                  Taslağı reddet
                </IslemDugmesi>
              </div>
            </div>
          )}
          {(uyari || islem.hata) && (
            <p className="alan-hata" role="alert">
              {uyari ?? islem.hata}
            </p>
          )}
          {!taslak && <Uyari ton="basari">Bu taslak için karar verildi; içerik artık değiştirilemez.</Uyari>}
        </form>
      </Kart>
    </>
  );
}
