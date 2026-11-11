import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import { useBildirim } from "../components/Bildirim";
import { BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { SCRIPT_DURUMU, scriptIsareti } from "../lib/etiketler";
import { YEREL_SINIF } from "../lib/kapi";
import { tarih } from "../lib/format";
import { PlatformRozeti, PlatformSecici } from "../components/Platform";
import { PLATFORM_ETIKETI, type Platform } from "../lib/platform";
import { DilRozeti, DilSecici } from "../components/Dil";
import { DIL_ETIKETI, dogrulanmamisDilMi, type Dil } from "../lib/dil";
import type { Script } from "../api/types";

/** Doğrulanmamış dil (C#, Python) seçiliyken üretim düğmesinin yanında duran açık uyarı. */
export const DOGRULANMAMIS_UYARISI = "Kod derlenmez ve koşulmaz; PR açılmaz.";

export function Kod() {
  const scriptler = useVeri(() => api.scriptler(), []);
  const caseler = useVeri(() => api.caseler(), []);
  const [secili, setSecili] = useState<Set<string>>(new Set());
  const [kapatilanlar, setKapatilanlar] = useState(false);
  // 009: üretimin hedef platformu (varsayılan Web). Aynı case her platformda ayrı script/PR alır.
  const [platform, setPlatform] = useState<Platform>("web");
  // 011: üretim dili ayrı boyuttur. Seçenekler ve repodan algılanan dil core'dan (`GET /code/languages`);
  // uç yoksa (011 öncesi core) `null` döner: seçici çizilmez, üretim bugünkü gibi sürer.
  const diller = useVeri(() => api.kodDilleri(platform), [platform]);
  // Kullanıcının elle seçtiği dil (yalnız algılanandan farklıysa); platform değişince sıfırlanır.
  const [elleDil, setElleDil] = useState<Dil | null>(null);
  const dilVerisi = diller.veri ?? null;
  const elleGecerli = !!dilVerisi && !!elleDil && dilVerisi.secenekler.some((s) => s.dil === elleDil && s.kullanilabilir) && elleDil !== dilVerisi.algilanan;
  const seciliDil: Dil | null = dilVerisi ? (elleGecerli && elleDil ? elleDil : dilVerisi.algilanan) : null;
  const seciliSecenek = dilVerisi?.secenekler.find((s) => s.dil === seciliDil) ?? null;
  const dogrulanmamis = seciliSecenek ? seciliSecenek.hat === "dogrulanmamis" : dogrulanmamisDilMi(seciliDil);
  // Algılanan dil bu depoda üretilemiyorsa (seçenek pasif) üretim başlatılmaz: neden seçenekte yazılıdır.
  const dilEngeli = seciliSecenek && !seciliSecenek.kullanilabilir ? (seciliSecenek.neden ?? `${seciliSecenek.etiket} bu depoda üretilemiyor.`) : null;
  const islem = useIslem();
  const bildir = useBildirim();
  const sessiz = useGeciktirilmis(() => {
    void scriptler.yenile(true);
  });
  useOlay(sessiz, ["agent.step", "pr.opened", "ci.status", "script.updated", "case.updated"]);

  // Kapatılmış (değişiklik istendi / reddedildi / yerine geçildi) test case'i yeniden üretime açar:
  // çekirdek kapalı script'ten sonra yeni üretimi kabul eder.
  // Aday: seçili platformda açık script'i olmayan onaylı case (başka platformdaki script'i engel değil).
  const scriptliCaseler = new Set(
    (scriptler.veri ?? []).filter((s) => s.durum !== "closed" && (s.platform === undefined ? "web" : s.platform) === platform).flatMap((s) => s.case_ids),
  );
  const adaylar = (caseler.veri ?? []).filter((c) => (c.durum === "approved" || c.durum === "published") && !scriptliCaseler.has(c.id));
  // Platform değişince başka platformda artık aday olmayan seçimler sayılmaz/gönderilmez.
  const seciliAdaylar = adaylar.filter((c) => secili.has(c.id)).map((c) => c.id);
  const tumScriptler = scriptler.veri ?? [];
  const kapaliSayisi = tumScriptler.filter((s) => s.durum === "closed").length;
  // Yeniden üretimle kapatılan eski kayıtlar varsayılan olarak gizlenir (aynı test iki kez görünmesin).
  const gorunen = kapatilanlar ? tumScriptler : tumScriptler.filter((s) => s.durum !== "closed");

  // Yeniden üretim script'in dilini taşır (dil değiştirmek ayrı karar: script detayında). Dil alanı yalnız
  // core dil boyutunu sunuyorsa gönderilir; 011 öncesi core'da gövde bugünküyle aynıdır.
  const yenidenUret = async (sc: Script, p: Platform) => {
    const dil = dilVerisi && sc.dil ? sc.dil : null;
    const s = await islem.calistir(() => (dil ? api.kodUret(sc.case_ids, p, dil) : api.kodUret(sc.case_ids, p)));
    if (s) {
      bildir(s.mesaj ?? "Yeniden üretim başladı; eski kayıt kapatılır.");
      void scriptler.yenile(true);
    }
  };

  return (
    <>
      <SayfaBasligi
        baslik="Kod üretimi"
        aciklama={
          dilVerisi
            ? "Onaylı case'ler seçilen platformda adım adım doğrulanır (Web: Playwright MCP; Android, iOS, Windows: Appium), page object'lere eşlenir ve seçilen dilde şablondan teste dönüşür. Model kod yazmaz; TypeScript ve Java'da yerel kontrol yeşilse bot ayrı dalda PR açar, C# ve Python kodu doğrulanmamış olarak çıkar."
            : "Onaylı case'ler seçilen platformda adım adım doğrulanır (Web: Playwright MCP; Android, iOS, Windows: Appium), page object'lere eşlenir ve şablondan teste dönüşür (Web: TypeScript, uygulamalar: Java). Model kod yazmaz; yerel kontrol yeşilse bot ayrı dalda PR açar."
        }
      />

      <Kart
        baslik="Kodu üretilecek onaylı case'ler"
        eylemler={
          <IslemDugmesi
            roller={["engineer"]}
            disabled={seciliAdaylar.length === 0 || !!dilEngeli}
            calisiyor={islem.calisiyor}
            title={dilEngeli ?? undefined}
            aria-describedby={dogrulanmamis ? "dogrulanmamis-dil-uyarisi" : undefined}
            onClick={async () => {
              // `dil` yalnız elle seçimde gönderilir (core `dil_kaynagi="secildi"`); aksi halde core algılar.
              const dil = elleGecerli ? seciliDil : null;
              const s = await islem.calistir(() => (dil ? api.kodUret(seciliAdaylar, platform, dil) : api.kodUret(seciliAdaylar, platform)));
              if (s) {
                bildir(s.mesaj ?? "Kod üretimi başladı.");
                setSecili(new Set());
                void scriptler.yenile(true);
                void caseler.yenile(true);
              }
            }}
          >
            Seçilenler için kod üret ({seciliAdaylar.length}){platform !== "web" && ` · ${PLATFORM_ETIKETI[platform]}`}
            {/* Dil düğmede yalnız algılanandan saparken yazılır; "doğrulanmamış" uyarısı düğmeye tanım olarak bağlı
                (390 px'te düğme adı kısa kalır, sayfa yatay kaymaz). */}
            {seciliDil && (elleGecerli || dogrulanmamis) && ` · ${DIL_ETIKETI[seciliDil]}`}
          </IslemDugmesi>
        }
      >
        <PlatformSecici
          etiket="Hedef platform"
          deger={platform}
          degistir={(p) => {
            // Bir platform için seçilen case başka platforma taşınmaz: seçim temizlenir.
            setPlatform(p);
            setSecili(new Set());
            // Dil seçenekleri platforma bağlıdır: elle seçim taşınmaz, yeni platformun algılananı gelir.
            setElleDil(null);
          }}
          disabled={islem.calisiyor}
          aciklamali
          dilAyri={!!dilVerisi}
          ipucu="Aynı onaylı case her platform için ayrı test ve ayrı PR olur; listede yalnızca bu platformda kodu üretilmemiş case'ler görünür."
        />
        {dilVerisi && seciliDil ? (
          <DilSecici
            diller={dilVerisi}
            deger={seciliDil}
            degistir={(d) => setElleDil(d === dilVerisi.algilanan ? null : d)}
            elle={elleGecerli}
            algilananaDon={() => setElleDil(null)}
            disabled={islem.calisiyor}
          />
        ) : diller.yukleniyor ? (
          <p className="kucuk soluk dil-yukleniyor" role="status">
            Dil seçenekleri yükleniyor…
          </p>
        ) : (
          diller.hata && (
            <Uyari ton="bilgi" baslik="Dil seçenekleri yüklenemedi">
              {diller.hata} Üretim, repodan algılanan dille sürer.{" "}
              <button type="button" className="dugme-metin" onClick={() => void diller.yenile()}>
                Yeniden dene
              </button>
            </Uyari>
          )
        )}
        {dogrulanmamis && seciliDil && (
          <div data-testid="dogrulanmamis-dil-uyarisi">
            <Uyari ton="uyari" baslik={`Doğrulanmamış dil: ${DIL_ETIKETI[seciliDil]}`} id="dogrulanmamis-dil-uyarisi">
              {DOGRULANMAMIS_UYARISI} Adımlar tarayıcıda yine doğrulanır; kod "Doğrulanmamış" etiketiyle çıkar, script detayından indirilir. Derleme,
              koşu ve PR için TypeScript ya da Java seçin.
            </Uyari>
          </div>
        )}
        {islem.hata && <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />}
        {caseler.yukleniyor && !caseler.veri ? (
          <Yukleniyor />
        ) : caseler.hata && !caseler.veri ? (
          <HataKutusu hata={caseler.hata} kaynak={caseler.hataNesnesi} yenile={() => void caseler.yenile()} />
        ) : adaylar.length === 0 ? (
          <BosDurum baslik={platform === "web" ? "Kodu üretilmemiş onaylı case yok." : `${PLATFORM_ETIKETI[platform]} için kodu üretilmemiş onaylı case yok.`} />
        ) : (
          <ul className="secim-liste">
            {adaylar.map((c) => (
              <li key={c.id}>
                <label>
                  <input
                    type="checkbox"
                    checked={secili.has(c.id)}
                    onChange={() =>
                      setSecili((s) => {
                        const y = new Set(s);
                        if (y.has(c.id)) y.delete(c.id);
                        else y.add(c.id);
                        return y;
                      })
                    }
                  />
                  <span className="mono">{c.jira_test_key ?? `${c.jira_key ?? "FT"} #${c.sira_no}`}</span> {c.icerik.title}
                </label>
                <div className="kucuk soluk secim-alt">Beklenen: {c.icerik.expected_result}</div>
              </li>
            ))}
          </ul>
        )}
      </Kart>

      <Kart
        baslik="Üretilen testler"
        eylemler={
          kapaliSayisi > 0 && (
            <label className="kucuk">
              <input type="checkbox" checked={kapatilanlar} onChange={(e) => setKapatilanlar(e.target.checked)} /> Kapatılanları göster ({kapaliSayisi})
            </label>
          )
        }
      >
        {scriptler.yukleniyor && !scriptler.veri ? (
          <Yukleniyor />
        ) : scriptler.hata && !scriptler.veri ? (
          <HataKutusu hata={scriptler.hata} kaynak={scriptler.hataNesnesi} yenile={() => void scriptler.yenile()} />
        ) : tumScriptler.length === 0 ? (
          <BosDurum baslik="Henüz üretilen test yok." />
        ) : gorunen.length === 0 ? (
          <BosDurum baslik="Açık üretilen test yok; kapatılanlar gizli." />
        ) : (
          <div className="tablo-sarici kod-tablosu" tabIndex={0} role="region" aria-label="Üretilen testler tablosu">
            <table className="tablo">
              <thead>
                <tr>
                  <th scope="col">Test</th>
                  <th scope="col">Durum</th>
                  <th scope="col">PR</th>
                  <th scope="col">Kırarak doğrula</th>
                  <th scope="col">Oluşturma</th>
                  <th scope="col">
                    <span className="gorunmez">Eylem</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {gorunen.map((s) => {
                  const d = SCRIPT_DURUMU[s.durum] ?? { etiket: s.durum, ton: "notr" as const };
                  const isaret = scriptIsareti(s);
                  const sinif = s.yerel_sinif && s.yerel_sinif !== "gecti" ? YEREL_SINIF[s.yerel_sinif] : null;
                  return (
                    <tr key={s.id}>
                      <td>
                        <Link to={`/kod/${encodeURIComponent(s.id)}`} className="satir-baglanti">
                          {s.baslik}
                        </Link>
                        <div className="satir-ogeler kucuk">
                          <PlatformRozeti platform={s.platform} />
                          {/* Dil rozeti yalnız core dil boyutunu sunuyorsa (alan uyarlayıcı varsayılanı değil, kayıtlı dil). */}
                          {dilVerisi && <DilRozeti dil={s.dil} platform={s.platform} />}
                          <span className="mono soluk">{s.dosya_yolu}</span>
                        </div>
                      </td>
                      <td>
                        <span className="satir-ogeler">
                          <Cip ton={d.ton}>{d.etiket}</Cip>
                          {isaret && (
                            <Cip ton={isaret.ton} title={isaret.aciklama}>
                              {isaret.etiket}
                            </Cip>
                          )}
                          {sinif && (
                            <Cip ton={sinif.ton} title={sinif.aciklama}>
                              {sinif.etiket}
                            </Cip>
                          )}
                          <ReplayRozeti mode={s.mode} />
                        </span>
                      </td>
                      <td>
                        {s.pr ? (
                          <span className="mono">#{s.pr.number} · {s.pr.durum === "merged" ? "birleşti" : s.pr.durum === "open" ? "açık" : "kapalı"}</span>
                        ) : s.durum === "unverified" ? (
                          <span className="soluk kucuk">Bu dilde yok</span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        {s.durum === "unverified" ? (
                          <span className="soluk kucuk">Bu dilde yok</span>
                        ) : s.break_verify.durum === "passed"
                          ? "✓ hata yakalıyor"
                          : s.break_verify.durum === "weak"
                            ? s.pr?.durum === "merged"
                              ? "Kırma etkilemedi · kabulle birleşti"
                              : "Kırma etkilemedi · kabul gerekli"
                            : s.break_verify.durum === "running"
                              ? "Sürüyor…"
                              : s.break_verify.durum === "failed"
                                ? "Tamamlanamadı"
                                : "—"}
                      </td>
                      <td className="tek-satir">{tarih(s.olusturma)}</td>
                      <td>
                        {/* Defect adayının testi doğru (uygulama farklı davranıyor): yeniden üretim önerilmez, karar triage'da. */}
                        {(s.durum === "blocked" || s.durum === "failed") &&
                          s.case_ids.length > 0 &&
                          s.platform !== null &&
                          !(s.yerel_sinif === "defect_adayi" || s.engel?.tur === "defect_candidate") && (
                          <IslemDugmesi
                            roller={["engineer"]}
                            tur="ikincil"
                            calisiyor={islem.calisiyor}
                            title="Aynı onaylı case için kodu yeniden üretir; bu kayıt kapatılır."
                            onClick={() => yenidenUret(s, s.platform === undefined ? "web" : (s.platform as Platform))}
                          >
                            Yeniden üret
                          </IslemDugmesi>
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
  );
}
