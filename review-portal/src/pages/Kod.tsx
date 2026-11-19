import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useOlay } from "../api/events";
import { useBildirim } from "../components/Bildirim";
import { BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, ReplayRozeti, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { DurumCipi, TabloSarici } from "../components/tasarim";
import { useGeciktirilmis, useIslem, useVeri } from "../hooks";
import { useIzin, usePlatformlar } from "../auth";
import { SCRIPT_DURUMU, scriptIsareti } from "../lib/etiketler";
import { YEREL_SINIF } from "../lib/kapi";
import { tarih } from "../lib/format";
import { PlatformRozeti, PlatformSecici } from "../components/Platform";
import { DepoCipi } from "../components/Depo";
import { PLATFORM_ETIKETI, type Platform } from "../lib/platform";
import { algilamaSuruyorMu, dilNedeni, DilRozeti, DilSecici, KurulumBilgisi, MusteriCiNotu, uretimAciklamasi } from "../components/Dil";
import { KurulumPrEylemi, MusteriCiKurulumYolu } from "../components/KurulumPrEylemi";
import { DIL_ETIKETI, type Dil } from "../lib/dil";
import { dikkatNedeni, GRUP_BASLIGI, scriptGrubu, type ScriptGrubu } from "../lib/kodDikkat";
import type { Script, UretimSonucu } from "../api/types";
import { baslamayanlar, DilCakismasiKutusu, dilCakismasiMi, UretimAtlananlar, uretimBildirimi } from "../components/UretimSonuclari";

/** Doğrulanmamış dil (C#, Python) seçiliyken üretim düğmesinin yanında duran açık uyarı. */
export const DOGRULANMAMIS_UYARISI = "Kod derlenmez ve koşulmaz; PR açılmaz.";

export const OTOMATIK_TETIK_ACIKLAMA = "Bu test, case onaylanınca otomatik kod üretimiyle başlatıldı (Otomasyon ayarı).";
export const OTOMATIK_TETIK_ROZETI = "Onay sonrası otomatik";
export const VERI_DEGISTI_METNI = "Test verisi değişti; yeniden üretin";
/** Projede (`/auth/me` → `ozellikler`) hiçbir platform açık değilken üretim formunun yerindeki bilgi. */
export const ACIK_PLATFORM_YOK = "Bu projede kod üretimi için açık platform yok.";

const SUREN_DURUMLAR = new Set(["pending", "verifying", "checking"]);
const scriptPlatformu = (s: Pick<Script, "platform">) => (s.platform === undefined ? "web" : s.platform);

/** Aynı case + platform için bu script'ten sonra üretilmiş başka script var mı (eski kayıt). */
export function dahaYeniScriptVar(s: Script, tum: readonly Script[]): boolean {
  const p = scriptPlatformu(s);
  return tum.some(
    (o) => o.id !== s.id && scriptPlatformu(o) === p && Date.parse(o.olusturma) > Date.parse(s.olusturma) && o.case_ids.some((c) => s.case_ids.includes(c)),
  );
}

/**
 * "Test verisi değişti" uyarısı ve yeniden üretim yalnız güncel kayıtta anlamlı: süren üretim
 * (pending/verifying/checking) bitmeden, kapatılmış ya da yerine yenisi üretilmiş eski kayıtta gösterilmez.
 */
export function veriDegistiGecerli(s: Script, tum: readonly Script[]): boolean {
  return !!s.veri_degisti && s.durum !== "closed" && !SUREN_DURUMLAR.has(s.durum) && !dahaYeniScriptVar(s, tum);
}

/** Değeri değişen anahtarların kısa metni (değer/özet gösterilmez). */
export const veriDegisenMetni = (s: Pick<Script, "veri_degisen">) =>
  s.veri_degisen && s.veri_degisen.length > 0 ? `Değeri değişen test verisi: ${s.veri_degisen.join(", ")}` : "Üretimde kullanılan test verisinin değeri katalogda değişti.";

/** 013 §3.5: otomatik tetik rozeti ve "test verisi değişti" işareti (core göndermediyse hiçbiri). */
export function OtomasyonIsaretleri({ s, veriUyarisi = !!s.veri_degisti }: { s: Pick<Script, "tetik" | "veri_degisti" | "veri_degisen">; veriUyarisi?: boolean }) {
  return (
    <>
      {s.tetik === "otomatik" && (
        <Cip ton="bilgi" title={OTOMATIK_TETIK_ACIKLAMA}>
          {OTOMATIK_TETIK_ROZETI}
        </Cip>
      )}
      {veriUyarisi && (
        <Cip ton="uyari" title={veriDegisenMetni(s)}>
          {VERI_DEGISTI_METNI}
        </Cip>
      )}
    </>
  );
}

export function Kod() {
  const scriptler = useVeri(() => api.scriptler(), []);
  const caseler = useVeri(() => api.caseler(), []);
  const [secili, setSecili] = useState<Set<string>>(new Set());
  const [kapatilanlar, setKapatilanlar] = useState(false);
  // 009: üretimin hedef platformu (varsayılan Web). Aynı case her platformda ayrı script/PR alır.
  const [seciliPlatform, setPlatform] = useState<Platform>("web");
  // Projede kapalı platform sunulmaz (`/auth/me` → `ozellikler`; alan yoksa dördü açık). Seçili platform
  // kapandıysa ilk açık platforma düşülür; hiç açık platform yoksa form yerine bilgi çizilir, üretim pasif.
  const acikPlatformlar = usePlatformlar();
  const platformYok = acikPlatformlar.length === 0;
  const platform: Platform = acikPlatformlar.includes(seciliPlatform) ? seciliPlatform : (acikPlatformlar[0] ?? seciliPlatform);
  // 011: üretim dili ayrı boyuttur. Seçenekler ve repodan algılanan dil core'dan (`GET /code/languages`);
  // uç yoksa (011 öncesi core) `null` döner: seçici çizilmez, üretim bugünkü gibi sürer.
  // `GET /code/languages` `code.generate` ya da `code.ci_setup` ister: üretebilen rol (Otomasyon Mühendisi) ve
  // müşteri CI kurulum PR'ını açabilen Sistem Yöneticisi okur (ekran testi 2 TP-4: yönetici seçiciyi salt
  // görüntüler, kurulum eylemine ulaşır); diğer rollerde istek atılmaz (konsolda 403 ve sahte `authz.denied` olmasın).
  const uretebilir = useIzin("code.generate");
  const ciKurabilir = useIzin("code.ci_setup");
  const dilOkur = uretebilir || ciKurabilir;
  const diller = useVeri(() => (dilOkur && !platformYok ? api.kodDilleri(platform) : Promise.resolve(null)), [platform, dilOkur && !platformYok]);
  // Kullanıcının elle seçtiği dil (yalnız algılanandan farklıysa); platform değişince sıfırlanır.
  const [elleDil, setElleDil] = useState<Dil | null>(null);
  const dilVerisi = diller.veri ?? null;
  // GitHub App kipinde algılama worker'da koşar; core sonucu beklerken süre dolduysa ("algılama
  // sürüyor") birkaç kez sessizce yeniden sorulur (T2-1).
  const [algilamaDenemesi, setAlgilamaDenemesi] = useState(0);
  const suruyor = algilamaSuruyorMu(dilVerisi);
  const { yenile: dilleriYenile } = diller;
  useEffect(() => setAlgilamaDenemesi(0), [platform]);
  useEffect(() => {
    if (!suruyor || algilamaDenemesi >= 5) return;
    const t = setTimeout(() => {
      setAlgilamaDenemesi((n) => n + 1);
      void dilleriYenile(true);
    }, 4000);
    return () => clearTimeout(t);
  }, [suruyor, algilamaDenemesi, dilleriYenile]);
  const elleGecerli = !!dilVerisi && !!elleDil && dilVerisi.secenekler.some((s) => s.dil === elleDil && s.kullanilabilir) && elleDil !== dilVerisi.algilanan;
  const seciliDil: Dil | null = dilVerisi ? (elleGecerli && elleDil ? elleDil : dilVerisi.algilanan) : null;
  const seciliSecenek = dilVerisi?.secenekler.find((s) => s.dil === seciliDil) ?? null;
  // Hat core'dan (`GET /code/languages`); seçenek yoksa bilinmez — uyarı uydurulmaz.
  const dogrulanmamis = seciliSecenek?.hat === "dogrulanmamis";
  const musteriCi = seciliSecenek?.hat === "musteri_ci";
  // Algılanan dil bu depoda üretilemiyorsa (seçenek pasif) üretim başlatılmaz: neden seçenekte yazılıdır.
  const dilEngeli = seciliSecenek && !seciliSecenek.kullanilabilir ? (dilNedeni(seciliSecenek.neden, platform).metin ?? `${seciliSecenek.etiket} bu depoda üretilemiyor.`) : null;
  const islem = useIslem();
  const bildir = useBildirim();
  // K-T12: son isteğin üretimi başlamayan case'leri (çakışma, açık/merge edilmiş PR, süren iş); yeni istekte sıfırlanır.
  const [atlananlar, setAtlananlar] = useState<UretimSonucu[]>([]);
  const caseAdi = (id: string) => {
    const c = (caseler.veri ?? []).find((x) => x.id === id);
    return c ? `${c.jira_test_key ?? `${c.jira_key ?? "FT"} #${c.sira_no}`} · ${c.icerik.title}` : null;
  };
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
  const gorunenHam = kapatilanlar ? tumScriptler : tumScriptler.filter((s) => s.durum !== "closed");
  // IA-13: dikkat gerekenler (insana düştü, başarısız, defect adayı, REPLAY-MISS, veri değişti) önce, süren/PR açık
  // sonra, birleşenler en sonda ve katlanabilir. Grup içinde core sırası korunur.
  const GRUP_SIRASI: ScriptGrubu[] = ["dikkat", "suren", "birlesen"];
  const gruplar = GRUP_SIRASI.map((g) => ({
    g,
    ogeler: gorunenHam.filter((s) => scriptGrubu(s, veriDegistiGecerli(s, tumScriptler)) === g),
  })).filter((x) => x.ogeler.length > 0);
  // Birleşenler, listede dikkat ya da süren kayıt varken varsayılan katlı; yalnız birleşen varsa açık.
  const [birlesenAcikSecim, setBirlesenAcik] = useState<boolean | null>(null);
  const birlesenAcik = birlesenAcikSecim ?? (kapatilanlar || gruplar.every((x) => x.g === "birlesen"));
  const gorunen = gorunenHam;
  // Kod üretim kuyruğu: herhangi bir açık platformda kodu üretilmemiş onaylı case var mı (seçici pano yalnız o zaman açık).
  const kuyrukBos = !!caseler.veri && adaylar.length === 0;

  // Yeniden üretim: dil yalnız kullanıcı onu elle seçtiyse (`dil_kaynagi="secildi"`) taşınır; algılanan ya da
  // varsayılan dilde `dil` gönderilmez, core yeniden algılar ve kaynak `algilandi` kalır (dil kaynağı
  // `secildi`'ye kaymaz). Dil değiştirmek ayrı karar: script detayında. 011 öncesi core'da gövde bugünküyle aynıdır.
  const yenidenUret = async (sc: Script, p: Platform) => {
    const dil = dilVerisi && sc.dil && sc.dil_kaynagi === "secildi" ? sc.dil : null;
    setAtlananlar([]);
    const s = await islem.calistir(() => (dil ? api.kodUret(sc.case_ids, p, dil) : api.kodUret(sc.case_ids, p)));
    if (s) {
      setAtlananlar(baslamayanlar(s));
      bildir(uretimBildirimi(s, "Yeniden üretim başladı; eski kayıt kapatılır."));
      void scriptler.yenile(true);
    }
  };

  return (
    <>
      <SayfaBasligi
        baslik="Kod üretimi"
        aciklama={
          dilVerisi
            ? uretimAciklamasi(dilVerisi)
            : "Onaylı case'ler seçilen platformda adım adım doğrulanır (Web: Playwright MCP; Android, iOS, Windows: Appium), page object'lere eşlenir ve şablondan teste dönüşür (Web: TypeScript, uygulamalar: Java). Model kod yazmaz; yerel kontrol yeşilse bot ayrı dalda PR açar."
        }
      />

      <Kart
        baslik="Kodu üretilecek onaylı case'ler"
        eylemler={
          // CL-09: boş kuyrukta kilitli "kod üret (0)" düğmesi gösterilmez (boş durum sonraki adımı söylüyor).
          !kuyrukBos && (
          <IslemDugmesi
            izin="code.generate"
            disabled={platformYok || seciliAdaylar.length === 0 || !!dilEngeli}
            calisiyor={islem.calisiyor}
            title={platformYok ? ACIK_PLATFORM_YOK : (dilEngeli ?? undefined)}
            aria-describedby={dogrulanmamis ? "dogrulanmamis-dil-uyarisi" : musteriCi ? "musteri-ci-notu" : undefined}
            onClick={async () => {
              // `dil` yalnız elle seçimde gönderilir (core `dil_kaynagi="secildi"`); aksi halde core algılar.
              const dil = elleGecerli ? seciliDil : null;
              setAtlananlar([]);
              const s = await islem.calistir(() => (dil ? api.kodUret(seciliAdaylar, platform, dil) : api.kodUret(seciliAdaylar, platform)));
              if (s) {
                setAtlananlar(baslamayanlar(s));
                bildir(uretimBildirimi(s, "Kod üretimi başladı."));
                setSecili(new Set());
                void scriptler.yenile(true);
                void caseler.yenile(true);
              }
            }}
          >
            Seçilenler için kod üret ({seciliAdaylar.length}){platform !== "web" && ` · ${PLATFORM_ETIKETI[platform]}`}
            {/* Dil düğmede yalnız algılanandan saparken yazılır; "doğrulanmamış" uyarısı düğmeye tanım olarak bağlı
                (390 px'te düğme adı kısa kalır, sayfa yatay kaymaz). */}
            {seciliDil && (elleGecerli || dogrulanmamis || musteriCi) && ` · ${DIL_ETIKETI[seciliDil]}`}
          </IslemDugmesi>
          )
        }
      >
        {platformYok ? (
          <div data-testid="acik-platform-yok">
            <Uyari ton="bilgi">{ACIK_PLATFORM_YOK}</Uyari>
          </div>
        ) : (
          <>
            {kuyrukBos && (
              /* IA-13: boş kuyruk kompakt tek satır; platform/dil panosu altta katlı özet. */
              <BosDurum
                kip="satir"
                baslik={platform === "web" ? "Kodu üretilecek onaylı case yok." : `${PLATFORM_ETIKETI[platform]} için kodu üretilecek onaylı case yok.`}
                eylem={
                  <>
                    <Link to="/caseler">Test case'lerine git</Link> · <Link to="/otomasyon">Otomasyon ayarı</Link>
                  </>
                }
              >
                Case'ler Analist son onayından sonra burada görünür; otomatik kod üretimi açıksa üretim kendiliğinden başlar.
              </BosDurum>
            )}
            <KuyrukPanosu katli={kuyrukBos} ozet={`${PLATFORM_ETIKETI[platform]}${seciliDil ? ` · ${DIL_ETIKETI[seciliDil]}` : ""}`}>
            {/* Üretim ayarları: platform → dil → dile bağlı notlar (doğrulanmamış, müşteri CI, kurulum PR'ı) tek blokta. */}
            <div className="kod-ayarlar" data-testid="kod-ayarlar">
            <PlatformSecici
              etiket="Hedef platform"
              platformlar={acikPlatformlar}
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
                // Üretemeyen rol (Sistem Yöneticisi) seçiciyi yalnız görüntüler.
                disabled={islem.calisiyor || !uretebilir}
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
            <div className="kod-dil-notlari">
            {dogrulanmamis && seciliDil && (
              <div data-testid="dogrulanmamis-dil-uyarisi">
                <Uyari ton="uyari" baslik={`Doğrulanmamış dil: ${DIL_ETIKETI[seciliDil]}`} id="dogrulanmamis-dil-uyarisi">
                  {DOGRULANMAMIS_UYARISI} Adımlar tarayıcıda yine doğrulanır; kod "Doğrulanmamış" etiketiyle çıkar, script detayından indirilir. Derleme,
                  koşu ve PR için TypeScript ya da Java seçin.
                </Uyari>
              </div>
            )}
            {musteriCi && seciliSecenek && <MusteriCiNotu etiket={seciliSecenek.etiket} id="musteri-ci-notu" />}
            {seciliSecenek?.kullanilabilir && <KurulumBilgisi kurulum={seciliSecenek.kurulum} dilEtiketi={seciliSecenek.etiket} />}
            {musteriCi && seciliSecenek?.kullanilabilir && (platform === "android" || platform === "ios") && (
              <KurulumPrEylemi key={`${platform}/${seciliSecenek.dil}`} platform={platform} kurulum={seciliSecenek.kurulum} degisti={() => void diller.yenile()} />
            )}
            {/* TP-1: seçilemeyen müşteri CI dili için de kurulum yolu (dil listesinde yok / depoda kurulu değil). */}
            {dilVerisi && ciKurabilir && <MusteriCiKurulumYolu platform={platform} secenekler={dilVerisi.secenekler} seciliDil={seciliDil} degisti={() => void diller.yenile()} />}
            </div>
            </div>
            {islem.hata &&
              (dilCakismasiMi(islem.hataNesnesi) ? <DilCakismasiKutusu hata={islem.hataNesnesi} /> : <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />)}
            </KuyrukPanosu>
            <UretimAtlananlar sonuclar={atlananlar} caseAdi={caseAdi} kapat={() => setAtlananlar([])} />
            {caseler.yukleniyor && !caseler.veri ? (
              <Yukleniyor />
            ) : caseler.hata && !caseler.veri ? (
              <HataKutusu hata={caseler.hata} kaynak={caseler.hataNesnesi} yenile={() => void caseler.yenile()} />
            ) : adaylar.length === 0 ? null : (
              <>
              {/* Sıradaki adım: aday listesi başlıklı, sayılı; tümünü seç / temizle tek dokunuş. */}
              <div className="kod-aday-baslik">
                <h3>
                  Bu platformda kodu üretilmemiş onaylı case'ler ({adaylar.length})
                </h3>
                {uretebilir && (
                  <button
                    type="button"
                    className="dugme dugme-metin dugme-kucuk"
                    disabled={islem.calisiyor}
                    onClick={() => setSecili(seciliAdaylar.length === adaylar.length ? new Set() : new Set(adaylar.map((c) => c.id)))}
                  >
                    {seciliAdaylar.length === adaylar.length ? "Seçimi temizle" : "Tümünü seç"}
                  </button>
                )}
              </div>
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
              </>
            )}
          </>
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
          <BosDurum baslik="Henüz üretilen test yok.">
            Onaylı case seçilip "kod üret" denince (ya da otomatik üretim açıksa onaydan sonra) testler burada listelenir (Otomasyon Mühendisi).
          </BosDurum>
        ) : gorunen.length === 0 ? (
          <BosDurum baslik="Açık üretilen test yok; kapatılanlar gizli." />
        ) : (
          /* ≤ 640 px'te satırlar kart olur (`tablo-yigin`): başlık ve dosya yolu kesilmez, sayfa yatay kaymaz.
             1024 px'te Oluşturma gizlenir, Eylem sağa yapışır (DZ-06). */
          <TabloSarici etiket="Üretilen testler tablosu" className="kod-tablosu" satirBaglanti>
              <thead>
                <tr>
                  <th scope="col">Test</th>
                  <th scope="col">Durum</th>
                  <th scope="col">PR</th>
                  <th scope="col">Kırarak doğrula</th>
                  <th scope="col" className="sutun-ikincil">Oluşturma</th>
                  <th scope="col" className="sutun-eylem">
                    <span className="gorunmez">Eylem</span>
                  </th>
                </tr>
              </thead>
              {gruplar.map(({ g, ogeler }) => (
              <tbody key={g} data-grup={g}>
                <tr className="kod-grup-satiri">
                  <th scope="colgroup" colSpan={6}>
                    {GRUP_BASLIGI[g]} ({ogeler.length})
                    {g === "birlesen" && gruplar.length > 1 && (
                      <>
                        {" "}
                        <button type="button" className="dugme dugme-hayalet dugme-kucuk" aria-expanded={birlesenAcik} onClick={() => setBirlesenAcik(!birlesenAcik)}>
                          {birlesenAcik ? "Gizle" : "Göster"}
                        </button>
                      </>
                    )}
                  </th>
                </tr>
                {(g === "birlesen" && !birlesenAcik ? [] : ogeler).map((s) => {
                  const isaret = scriptIsareti(s);
                  const neden = dikkatNedeni(s, veriDegistiGecerli(s, tumScriptler));
                  const sinif = s.yerel_sinif && s.yerel_sinif !== "gecti" ? YEREL_SINIF[s.yerel_sinif] : null;
                  const yenidenUretilebilir =
                    (s.durum === "blocked" || s.durum === "failed" || veriDegistiGecerli(s, tumScriptler)) &&
                    s.case_ids.length > 0 &&
                    s.platform !== null &&
                    // Projede kapanan platformun kaydı yeniden üretilmez (core 409 `ozellik_kapali`).
                    acikPlatformlar.includes(scriptPlatformu(s) as Platform) &&
                    !(s.yerel_sinif === "defect_adayi" || s.engel?.tur === "defect_candidate");
                  return (
                    <tr key={s.id}>
                      <td className="yigin-baslik sutun-metin" data-etiket="Test">
                        <Link to={`/kod/${encodeURIComponent(s.id)}`} className="satir-baglanti">
                          {s.baslik}
                        </Link>
                        <div className="satir-ogeler kucuk">
                          <PlatformRozeti platform={s.platform} />
                          {/* Platform deposu (varsayılan dışı depoda sahip/ad; PR'ı da o depoda). */}
                          <DepoCipi kaynak={s} />
                          {/* Dil rozeti yalnız core dil boyutunu sunuyorsa (alan uyarlayıcı varsayılanı değil, kayıtlı dil). */}
                          {dilVerisi && <DilRozeti dil={s.dil} platform={s.platform} />}
                        </div>
                        {neden && (
                          <div className="kucuk kod-neden" data-testid="kod-neden">
                            <strong>{neden.metin}</strong>
                            {neden.ayrinti && <span className="soluk"> — {neden.ayrinti}</span>}
                            {neden.eylem?.tur === "baglanti" && (
                              <>
                                {" "}
                                <Link to={neden.eylem.yol}>{neden.eylem.etiket} →</Link>
                              </>
                            )}
                          </div>
                        )}
                        {/* Dosya yolu ikincil bilgi: yalnız dosya adı, tam yol ipucunda. */}
                        <div className="mono soluk kucuk kod-satir-dosya" title={s.dosya_yolu}>
                          {s.dosya_yolu.split("/").pop()}
                        </div>
                      </td>
                      <td className="sutun-durum" data-etiket="Durum">
                        <span className="satir-ogeler">
                          <DurumCipi harita={SCRIPT_DURUMU} deger={s.durum} />
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
                          <OtomasyonIsaretleri s={s} veriUyarisi={veriDegistiGecerli(s, tumScriptler)} />
                        </span>
                      </td>
                      <td data-etiket="PR">
                        {s.pr ? (
                          <span className="mono">#{s.pr.number} · {s.pr.durum === "merged" ? "birleşti" : s.pr.durum === "open" ? "açık" : "kapalı"}</span>
                        ) : s.durum === "unverified" ? (
                          <span className="soluk kucuk">Bu dilde yok</span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td data-etiket="Kırarak doğrula">
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
                      <td className="sutun-tarih sutun-ikincil" data-etiket="Oluşturma">
                        {tarih(s.olusturma)}
                      </td>
                      <td className={yenidenUretilebilir ? "sutun-eylem" : "sutun-eylem bos-hucre"} data-etiket="Eylem">
                        {/* Defect adayının testi doğru (uygulama farklı davranıyor): yeniden üretim önerilmez, karar triage'da. */}
                        {/* 013: test verisi değişen güncel script de yeniden üretilebilir (süren / eski kayıtta değil). */}
                        {yenidenUretilebilir && (
                          <IslemDugmesi
                            izin="code.generate"
                            tur="ikincil"
                            calisiyor={islem.calisiyor}
                            title={
                              s.durum === "blocked" || s.durum === "failed"
                                ? "Aynı onaylı case için kodu yeniden üretir; bu kayıt kapatılır."
                                : s.durum === "unverified"
                                  ? "Kodu güncel test verisiyle yeniden üretir (doğrulanmamış dil; PR açılmaz)."
                                  : s.durum === "merged"
                                    ? "Kodu güncel test verisiyle yeniden üretir; birleşmiş kayıt değişmez, yeni PR açılır."
                                    : "Kodu güncel test verisiyle yeniden üretir; bu kayıt ve açık PR'ı kapatılır, yenisi açılır."
                            }
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
              ))}
          </TabloSarici>
        )}
      </Kart>
    </>
  );
}

/**
 * IA-13: platform/dil seçici panosu. Kod üretim kuyruğu boşken ekranı kaplamaz: tek satırlık katlı bölümde
 * ("Platform ve dil: Web · TypeScript") durur; kuyrukta case varken olduğu gibi açık çizilir.
 */
function KuyrukPanosu({ katli, ozet, children }: { katli: boolean; ozet: string; children: ReactNode }) {
  if (!katli) return <>{children}</>;
  return (
    <details className="kod-pano-katli" data-testid="kod-pano-katli">
      <summary>Platform ve dil ayarları: {ozet}</summary>
      {children}
    </details>
  );
}
