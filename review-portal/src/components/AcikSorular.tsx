// Açık soru döngüsü (specs/011 K16; D6): "Açık soruları PO'ya gönder" paneli, case kartındaki
// soru durumu/yanıtı, düzeltme formunda yanıt metni ve "düzelt / yeniden üret" önerisi.
// PO yanıtı Jira yorumundan gelen güvenilmeyen düz metindir: yalnız metin düğümü olarak yazılır.
import { useEffect, useId, useRef, useState } from "react";
import {
  ACIK_SORU_DURUMU,
  type AcikSoruKaydi,
  type AcikSoruDurumu,
  type AcikSorularYaniti,
} from "../api/acikSoruTipleri";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import type { AcikSoru, PoSoruDurumu, TestCase, Varsayim } from "../api/types";
import { useKisiAdi } from "../auth";
import { useIslem, useVeri } from "../hooks";
import { dogrulamaNotu, storySiYok } from "../lib/caseV3";
import { useBildirim } from "./Bildirim";
import { CASE_HAZIRLIK, SORU_SAHIBI } from "../lib/etiketler";
import { tarih } from "../lib/format";
import {
  AlanHatasi,
  BosDurum,
  Cip,
  HataKutusu,
  IslemDugmesi,
  Kart,
  Uyari,
  Yukleniyor,
} from "./ui";

export const GONDER_ACIKLAMASI =
  "Gönderilmemiş sorular story'ye tek Jira yorumu olarak, PO'nun yanıtta kullanacağı kimlikle (CQ1, CA1 …) ve bekleyen case'lerle yazılır. Aynı soru ikinci kez gönderilmez.";

/** Soru kaydının PO durumu rozeti ("PO'ya gönderilmedi" / "PO yanıtı bekleniyor" / "Yanıtlandı"). */
export function PoDurumRozeti({
  durum,
  etiket,
}: {
  durum: AcikSoruDurumu;
  etiket?: string | null;
}) {
  const d = ACIK_SORU_DURUMU[durum];
  return (
    <Cip ton={d.ton} title={d.aciklama}>
      {etiket ? `${etiket} · ` : ""}
      {d.etiket}
    </Cip>
  );
}

/**
 * B17: PO yanıtının yazarı görünen adıyla. Core Jira görünen adını, yoksa "PO" etiketini yazar;
 * eski kayıtta e-posta kalmışsa ve kullanıcı adı eşlenemiyorsa e-posta (ya da yerel kısmı)
 * gösterilmez. "PO" etiketi tekrar edilmez: satır zaten "— PO yanıtı" der.
 */
export function poYazarAdi(yazar: string | null, kisiAdi: (k: string) => string): string {
  if (!yazar) return "";
  const ad = kisiAdi(yazar).trim();
  return ad.includes("@") || ad === "PO" ? "" : ad;
}

/** PO yanıtı: düz metin (güvenilmeyen), yazar ve zaman. */
export function PoYanitiMetni({
  yanit,
}: {
  yanit: { metin: string; yazar: string | null; zaman: string | null };
}) {
  // B17: yazar görünen adıyla (kullanıcı adı eşlenemezse — Jira görünen adı — aynen).
  const kisiAdi = useKisiAdi();
  const ek = [poYazarAdi(yanit.yazar, kisiAdi), yanit.zaman ? tarih(yanit.zaman) : ""].filter(Boolean).join(", ");
  return (
    <blockquote className="po-yaniti" data-testid="po-yaniti">
      <span className="po-yaniti-metin">{yanit.metin}</span>
      <span className="soluk kucuk" data-testid="po-yaniti-kaynak">
        {" "}
        — PO yanıtı{ek ? ` (${ek})` : ""}
      </span>
    </blockquote>
  );
}

/**
 * B15 / B2: varsayım rozeti. Başka case'te doğrulandıysa "Doğrulandı (#2)"; PO'ya gönderilmemiş ve sahibi
 * PO olmayan varsayımda "Doğrulanmadı" (PO rozeti yalnız gönderilince); diğer durumlarda PO durumu.
 */
export function VarsayimRozeti({
  durum,
  sahip,
  dogrulama,
}: {
  durum: AcikSoruDurumu | undefined;
  sahip: string;
  dogrulama?: Varsayim["dogrulama"];
}) {
  const kisiAdi = useKisiAdi();
  if (dogrulama) {
    return (
      <Cip ton="basari" title={dogrulamaNotu({ id: dogrulama.kimlik ?? "Varsayım", dogrulama }, kisiAdi) ?? undefined}>
        <span data-testid="varsayim-dogrulandi">✓ Doğrulandı (#{dogrulama.sira_no})</span>
      </Cip>
    );
  }
  if (!durum) return null;
  if (durum === "gonderilmedi" && sahip !== "PO") {
    return (
      <Cip ton="notr" title="Varsayım henüz doğrulanmadı. Doğrulamayı Testçi yapar (Varsayım doğrulandı düğmesi); Analist isterse PO'ya da gönderebilir.">
        Doğrulanmadı
      </Cip>
    );
  }
  return <PoDurumRozeti durum={durum} />;
}

/**
 * Case kartındaki atıf satırının PO bölümü (alan yoksa — eski core — hiçbir şey çizilmez). Kimlik (CQ1)
 * satır başında yazılır (B7); rozet yalnız durumu söyler. Varsayımda `VarsayimRozeti` (B2/B15).
 */
export function AtifPoDurumu({ kayit, varsayim }: { kayit: PoSoruDurumu & { owner?: string; dogrulama?: Varsayim["dogrulama"] }; varsayim?: boolean }) {
  if (varsayim) {
    if (!kayit.po_durumu && !kayit.dogrulama) return null;
    return (
      <>
        {" "}
        <VarsayimRozeti durum={kayit.po_durumu} sahip={kayit.owner ?? ""} dogrulama={kayit.dogrulama} />
        {kayit.po_yaniti && <PoYanitiMetni yanit={kayit.po_yaniti} />}
      </>
    );
  }
  if (!kayit.po_durumu) return null;
  return (
    <>
      {" "}
      <PoDurumRozeti durum={kayit.po_durumu} />
      {kayit.po_yaniti && <PoYanitiMetni yanit={kayit.po_yaniti} />}
    </>
  );
}

/** Yanıtlanan soruya bağlı taslak case için öneri kutusu. */
export function PoYanitOnerisi({ tc }: { tc: TestCase }) {
  const o = tc.po_yanit_onerisi;
  if (!o) return null;
  return (
    <div data-testid="po-yanit-onerisi">
      <Uyari
        ton="bilgi"
        baslik={`PO yanıtladı (${o.etiketler.join(", ")}): düzelt ya da yeniden üret`}
      >
        {o.mesaj}
      </Uyari>
    </div>
  );
}

/**
 * Düzeltme formunda: yanıtlanan soruların/varsayımların PO yanıtı — beklenen sonucun kaynağı.
 * Atıf kaldırılıp case hazır yapıldığında denetim kaydına "kaynak: PO yanıtı CQn" yazılır.
 */
export function DuzeltmeKaynaklari({
  sorular = [],
  varsayimlar = [],
}: {
  sorular?: AcikSoru[];
  varsayimlar?: Varsayim[];
}) {
  const yanitli = [
    ...sorular
      .filter((q) => q.po_yaniti)
      .map((q) => ({
        id: q.id,
        etiket: q.po_etiketi,
        metin: q.question,
        yanit: q.po_yaniti!,
      })),
    ...varsayimlar
      .filter((a) => a.po_yaniti)
      .map((a) => ({
        id: a.id,
        etiket: a.po_etiketi,
        metin: a.statement,
        yanit: a.po_yaniti!,
      })),
  ];
  if (yanitli.length === 0) return null;
  return (
    <div data-testid="duzeltme-kaynaklari">
      <Uyari ton="bilgi" baslik="Beklenen sonucun kaynağı: PO yanıtı">
        <ul className="case-atif-listesi">
          {yanitli.map((y) => (
            <li key={y.id}>
              <span className="mono ac-ref">{y.etiket ?? y.id}</span> {y.metin}
              <PoYanitiMetni yanit={y.yanit} />
            </li>
          ))}
        </ul>
        <p className="soluk kucuk">
          Beklenen sonucu yanıta göre yazın, ilgili soru/varsayım atfını
          kaldırın ve durumu "Hazır" yapın; denetim kaydına kaynak olarak PO
          yanıtı yazılır.
        </p>
      </Uyari>
    </div>
  );
}

function SoruSatiri({ s, dogrulama }: { s: AcikSoruKaydi; dogrulama?: Varsayim["dogrulama"] }) {
  return (
    <li className="acik-soru" data-testid="acik-soru-satiri">
      <div className="satir-ogeler">
        <span className="mono ac-ref" title={s.etiket ? `Üretimdeki kimlik: ${s.kaynak_id}` : undefined}>
          {s.etiket ?? s.kaynak_id}
        </span>
        {/* B7: gönderilen soru PO'nun gördüğü kimlikle anılır; üretimdeki kimlik yalnız ipucu. */}
        {s.etiket && <span className="soluk kucuk">üretimdeki kimlik: {s.kaynak_id}</span>}
        {/* UX4 Bulgu 9: yanıtlanan soru artık "açık" değildir. */}
        <Cip ton="notr">{s.tur === "soru" ? (s.durum === "yanitlandi" ? "Soru" : "Açık soru") : "Varsayım"}</Cip>
        {s.tur === "varsayim" ? <VarsayimRozeti durum={s.durum} sahip={s.sahip} dogrulama={dogrulama} /> : <PoDurumRozeti durum={s.durum} />}
        <span className="soluk kucuk">
          Sahibi: {SORU_SAHIBI[s.sahip] ?? s.sahip}
        </span>
      </div>
      <p>{s.metin}</p>
      {s.gonderim_belirsiz && (
        <p className="soluk kucuk" data-testid="gonderim-belirsiz">
          Gönderim sonucu belirsiz: yorum Jira'ya yazılmış olabilir. Yeniden gönderin; aynı yorum
          ikinci kez yazılmaz.
        </p>
      )}
      {s.yanit && <PoYanitiMetni yanit={s.yanit} />}
      {s.bekleyen_caseler.length > 0 && (
        <p className="kucuk">
          {s.tur === "soru" ? "Bekleyen case'ler" : "Dayanan case'ler"}:{" "}
          {s.bekleyen_caseler.map((c, i) => (
            <span key={c.id}>
              {i > 0 && " · "}
              <a href={`#case-${c.id}`}>
                #{c.sira_no} {c.title}
              </a>{" "}
              <Cip
                ton={(CASE_HAZIRLIK[c.readiness] ?? CASE_HAZIRLIK.ready).ton}
              >
                {(CASE_HAZIRLIK[c.readiness] ?? CASE_HAZIRLIK.ready).etiket}
              </Cip>
            </span>
          ))}
        </p>
      )}
      {s.oneri && (
        <p className="kucuk" data-testid="acik-soru-onerisi">
          <strong>Öneri:</strong> {s.oneri.mesaj}
        </p>
      )}
    </li>
  );
}

/** CaseReview: güncel setin açık soruları, PO durumu ve "Açık soruları PO'ya gönder". */
/** Panel sayacı ve gönder düğmesinin nedeni (B6): sorular ve varsayımlar ayrı sayılır. */
export function panelSayimi(
  sorular: AcikSoruKaydi[],
  varsayimlarDahil: boolean,
  jiraEngeli: string | null,
  /** UX4 Bulgu 9: başka case'te doğrulanmış (B2) gönderilmemiş varsayım "gönderilmedi" sayılmaz. */
  dogrulanmis: (k: AcikSoruKaydi) => boolean = () => false,
) {
  const say = (tur: "soru" | "varsayim") => {
    const s = { gonderilmedi: 0, gonderildi: 0, yanitlandi: 0 };
    for (const k of sorular) if (k.tur === tur && !(tur === "varsayim" && k.durum === "gonderilmedi" && dogrulanmis(k))) s[k.durum] += 1;
    return s;
  };
  const soru = say("soru");
  const varsayim = say("varsayim");
  const varsayimVar = sorular.some((k) => k.tur === "varsayim");
  const parca = (s: typeof soru, tam: boolean) =>
    (
      [
        [s.gonderilmedi, "gönderilmedi"],
        [s.gonderildi, "yanıt bekleniyor"],
        [s.yanitlandi, "yanıtlandı"],
      ] as const
    )
      .filter(([n]) => tam || n > 0)
      .map(([n, e]) => `${n} ${e}`)
      .join(" · ");
  const dogrulanan = sorular.filter((k) => k.tur === "varsayim" && k.durum === "gonderilmedi" && dogrulanmis(k)).length;
  const varsayimMetni = [parca(varsayim, false), dogrulanan ? `${dogrulanan} doğrulandı` : ""].filter(Boolean).join(" · ");
  const metin = `Sorular: ${parca(soru, true)}${varsayimVar ? ` | Varsayımlar: ${varsayimMetni || "—"}` : ""}`;
  const gonderilecek = soru.gonderilmedi + (varsayimlarDahil ? varsayim.gonderilmedi : 0);
  const neden = jiraEngeli
    ? jiraEngeli
    : gonderilecek > 0
      ? undefined
      : varsayim.gonderilmedi > 0
        ? `Gönderilmemiş soru yok; ${varsayim.gonderilmedi} varsayım gönderilmedi. Göndermek için "Case'lerin dayandığı varsayımları da doğrulama için gönder" kutusunu işaretleyin.`
        : "Gönderilmemiş soru ya da varsayım yok.";
  return { metin, gonderilecek, neden };
}

const normal = (m: string) => m.split(/\s+/).filter(Boolean).join(" ").toLocaleLowerCase("tr");

export function AcikSorularPaneli({
  requirementId,
  tazele,
  caseler,
  veriDegisti,
}: {
  requirementId: string;
  tazele?: () => void;
  /** Panelin core verisi değişince (yükleme, gönderim, yanıt okuma) sayfaya bildirilir: durum şeridi ve toplu onay aynı listeyi kullanır. */
  veriDegisti?: (v: AcikSorularYaniti | null) => void;
  /**
   * Sayfanın case listesi: varsayımın başka case'te doğrulandığı bilgisi (B2) buradan okunur; case
   * kartından yapılan gönderim/yanıt (PO durumu değişimi) paneli sessizce tazeler.
   */
  caseler?: TestCase[];
}) {
  const durum = useVeri(
    () =>
      api.acikSorular(requirementId).catch((e: unknown) => {
        // Eski core (uç yok): panel gösterilmez.
        if (e instanceof ApiError && (e.status === 404 || e.status === 501))
          return null;
        throw e;
      }),
    [requirementId],
  );
  const [varsayimlar, setVarsayimlar] = useState(false);
  const [islem, setIslem] = useState<"gonder" | "oku" | null>(null);
  const [hata, setHata] = useState<string | null>(null);
  const id = useId();
  // Case listesindeki PO durumları değişince (kartın "PO'ya gönder"i) panel sessizce yeniden okunur.
  const imza = JSON.stringify((caseler ?? []).map((c) => [c.id, c.po_sorulari ?? null]));
  const oncekiImza = useRef(imza);
  const { yenile } = durum;
  useEffect(() => {
    if (durum.veri !== undefined) veriDegisti?.(durum.veri);
  }, [durum.veri, veriDegisti]);
  useEffect(() => {
    if (oncekiImza.current === imza) return;
    oncekiImza.current = imza;
    void yenile(true);
  }, [imza, yenile]);
  // B2: varsayım metni → başka case'te doğrulama (core `varsayimlar[].dogrulama`).
  const dogrulamalar = new Map<string, NonNullable<Varsayim["dogrulama"]>>();
  for (const c of caseler ?? []) for (const a of c.varsayimlar ?? []) if (a.dogrulama && !dogrulamalar.has(normal(a.statement))) dogrulamalar.set(normal(a.statement), a.dogrulama);

  const calistir = async (tur: "gonder" | "oku") => {
    setIslem(tur);
    setHata(null);
    try {
      durum.setVeri(
        tur === "gonder"
          ? await api.acikSorulariGonder(requirementId, varsayimlar)
          : await api.acikSoruYanitlariniOku(requirementId),
      );
      tazele?.();
    } catch (e) {
      setHata(e instanceof Error ? e.message : String(e));
    } finally {
      setIslem(null);
    }
  };

  if (durum.veri === null) return null;
  const v = durum.veri;
  const dogrulanmis = (s: AcikSoruKaydi) => s.tur === "varsayim" && dogrulamalar.has(normal(s.metin));
  const varsayimVar = !!v?.sorular.some(
    (s) => s.tur === "varsayim" && s.durum === "gonderilmedi" && !dogrulanmis(s),
  );
  const sayim = panelSayimi(v?.sorular ?? [], varsayimlar, v && !v.jira_key ? (v.gonderim_engeli ?? "Gereksinimin Jira story'si yok.") : null, dogrulanmis);
  const bekleyenVar = !!v?.sorular.some((s) => s.durum === "gonderildi");
  // B14: dar ekranda iki düğmenin nedeni alt alta düşer; her neden hangi düğmeye ait olduğunu söyler.
  const gonderNedeni = sayim.neden ? `Gönderim: ${sayim.neden}` : undefined;

  return (
    <Kart
      baslik="Açık sorular ve PO yanıtları"
      id="acik-sorular"
      eylemler={
        v && v.sorular.length > 0 ? (
          <>
            <IslemDugmesi
              izin="case.ask_po"
              calisiyor={islem === "gonder"}
              disabled={!!gonderNedeni || islem !== null}
              title={gonderNedeni ?? GONDER_ACIKLAMASI}
              onClick={() => void calistir("gonder")}
            >
              Açık soruları PO'ya gönder
            </IslemDugmesi>
            <IslemDugmesi
              izin={["case.ask_po", "case.decide"]}
              tur="ikincil"
              calisiyor={islem === "oku"}
              disabled={!bekleyenVar || islem !== null}
              title={
                bekleyenVar
                  ? "PO'nun story'ye yazdığı yanıtları şimdi oku"
                  : "Yanıt kontrolü: yanıt bekleyen soru yok."
              }
              onClick={() => void calistir("oku")}
            >
              Yanıtları kontrol et
            </IslemDugmesi>
          </>
        ) : undefined
      }
    >
      {durum.yukleniyor && !v && <Yukleniyor />}
      {durum.hata && (
        <HataKutusu
          hata={durum.hata}
          yenile={() => void durum.yenile()}
          kaynak={durum.hataNesnesi}
        />
      )}
      {hata && (
        <Uyari baslik="İşlem yapılamadı">
          <span data-testid="acik-soru-hata">{hata}</span>
        </Uyari>
      )}
      {v && v.sorular.length === 0 && (
        <BosDurum baslik="Açık soru yok">
          Güncel case setinde yanıt bekleyen soru ya da doğrulama bekleyen
          varsayım yok.
        </BosDurum>
      )}
      {v && v.sorular.length > 0 && (
        <>
          <p className="soluk kucuk" data-testid="acik-soru-sayim">
            {sayim.metin}
          </p>
          {varsayimVar && (
            <label className="kucuk" htmlFor={`${id}-varsayim`}>
              <input
                id={`${id}-varsayim`}
                type="checkbox"
                checked={varsayimlar}
                onChange={(e) => setVarsayimlar(e.target.checked)}
              />{" "}
              Case'lerin dayandığı varsayımları da doğrulama için gönder
            </label>
          )}
          <ul className="acik-soru-listesi">
            {v.sorular.map((s) => (
              <SoruSatiri
                key={`${s.tur}-${s.kaynak_id}-${s.etiket ?? ""}`}
                s={s}
                dogrulama={s.tur === "varsayim" ? dogrulamalar.get(normal(s.metin)) : undefined}
              />
            ))}
          </ul>
        </>
      )}
    </Kart>
  );
}

/**
 * D5 × D6: soru bekleyen case kartındaki "Neden onaylanamıyor" kutusunun eylemi (`poyaGonder`
 * yuvası). Case'in atıf yaptığı sorulardan biri henüz gönderilmediyse "Açık soruları PO'ya gönder"
 * gereksinimin gönderilmemiş sorularını story'ye tek Jira yorumu olarak yollar; sonra liste yenilenir.
 * Hepsi gönderildiyse/yanıtlandıysa eylem çizilmez (durum kutunun metninde).
 */
export function PoyaGonderEylemi({ tc, tamamlandi }: { tc: TestCase; tamamlandi?: () => void }) {
  const islem = useIslem();
  const bildir = useBildirim();
  const sorular = tc.icerik.open_question_refs ?? [];
  const po = tc.po_sorulari;
  const gonderilmemis = sorular.filter((q) => !po || (po[q]?.po_durumu ?? "gonderilmedi") === "gonderilmedi");
  if (sorular.length === 0 || gonderilmemis.length === 0) return null;
  // B1: story'si olmayan gereksinimde soru portaldan gönderilemez (core 409); düğme çizilmez, nedeni
  // kutunun metninde ("yanıtı PO'dan alıp 'Düzelt' ile …").
  if (storySiYok(tc)) return null;
  const gonder = async () => {
    const y = await islem.calistir(() => api.acikSorulariGonder(tc.requirement_id));
    if (y) {
      // B7: bildirimde PO'nun göreceği kimlik (CQ1).
      const etiketler = gonderilmemis.map((q) => y.sorular?.find((s) => s.tur === "soru" && s.kaynak_id === q)?.etiket ?? q);
      bildir(`Açık sorular PO'ya gönderildi (${etiketler.join(", ")}); yanıt gelince case'e bağlanır.`);
      tamamlandi?.();
    }
  };
  return (
    <div className="eylemler">
      <IslemDugmesi izin="case.ask_po" kucuk tur="ikincil" calisiyor={islem.calisiyor} title={GONDER_ACIKLAMASI} nedenGizli onClick={() => void gonder()}>
        Açık soruları PO'ya gönder
      </IslemDugmesi>
      {islem.hata && <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>{islem.hata}</AlanHatasi>}
    </div>
  );
}
