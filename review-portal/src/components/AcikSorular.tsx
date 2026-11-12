// Açık soru döngüsü (specs/011 K16; D6): "Açık soruları PO'ya gönder" paneli, case kartındaki
// soru durumu/yanıtı, düzeltme formunda yanıt metni ve "düzelt / yeniden üret" önerisi.
// PO yanıtı Jira yorumundan gelen güvenilmeyen düz metindir: yalnız metin düğümü olarak yazılır.
import { useId, useState } from "react";
import {
  ACIK_SORU_DURUMU,
  type AcikSoruKaydi,
  type AcikSoruDurumu,
} from "../api/acikSoruTipleri";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import type { AcikSoru, PoSoruDurumu, TestCase, Varsayim } from "../api/types";
import { useIslem, useVeri } from "../hooks";
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

/** PO yanıtı: düz metin (güvenilmeyen), yazar ve zaman. */
export function PoYanitiMetni({
  yanit,
}: {
  yanit: { metin: string; yazar: string | null; zaman: string | null };
}) {
  return (
    <blockquote className="po-yaniti" data-testid="po-yaniti">
      <span className="po-yaniti-metin">{yanit.metin}</span>
      <span className="soluk kucuk">
        {" "}
        — PO yanıtı{yanit.yazar ? ` (${yanit.yazar}` : ""}
        {yanit.yazar && yanit.zaman
          ? `, ${tarih(yanit.zaman)})`
          : yanit.yazar
            ? ")"
            : yanit.zaman
              ? ` (${tarih(yanit.zaman)})`
              : ""}
      </span>
    </blockquote>
  );
}

/** Case kartındaki atıf satırının PO bölümü (alan yoksa — eski core — hiçbir şey çizilmez). */
export function AtifPoDurumu({ kayit }: { kayit: PoSoruDurumu }) {
  if (!kayit.po_durumu) return null;
  return (
    <>
      {" "}
      <PoDurumRozeti durum={kayit.po_durumu} etiket={kayit.po_etiketi} />
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

function SoruSatiri({ s }: { s: AcikSoruKaydi }) {
  return (
    <li className="acik-soru" data-testid="acik-soru-satiri">
      <div className="satir-ogeler">
        <span className="mono ac-ref">{s.etiket ?? s.kaynak_id}</span>
        <Cip ton="notr">{s.tur === "soru" ? "Açık soru" : "Varsayım"}</Cip>
        <PoDurumRozeti durum={s.durum} />
        <span className="soluk kucuk">
          Sahibi: {SORU_SAHIBI[s.sahip] ?? s.sahip}
        </span>
      </div>
      <p>{s.metin}</p>
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
export function AcikSorularPaneli({
  requirementId,
  tazele,
}: {
  requirementId: string;
  tazele?: () => void;
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
  const varsayimVar = !!v?.sorular.some(
    (s) => s.tur === "varsayim" && s.durum === "gonderilmedi",
  );
  const gonderilecek = v
    ? v.sorular.filter(
        (s) => s.durum === "gonderilmedi" && (varsayimlar || s.tur === "soru"),
      ).length
    : 0;
  const bekleyenVar = !!v?.sorular.some((s) => s.durum === "gonderildi");
  const gonderNedeni = !v?.jira_key
    ? (v?.gonderim_engeli ?? undefined)
    : gonderilecek === 0
      ? "Gönderilmemiş açık soru yok."
      : undefined;

  return (
    <Kart
      baslik="Açık sorular ve PO yanıtları"
      id="acik-sorular"
      eylemler={
        v && v.sorular.length > 0 ? (
          <>
            <IslemDugmesi
              roller={["analyst"]}
              calisiyor={islem === "gonder"}
              disabled={!!gonderNedeni || islem !== null}
              title={gonderNedeni ?? GONDER_ACIKLAMASI}
              onClick={() => void calistir("gonder")}
            >
              Açık soruları PO'ya gönder
            </IslemDugmesi>
            <IslemDugmesi
              roller={["analyst"]}
              tur="ikincil"
              calisiyor={islem === "oku"}
              disabled={!bekleyenVar || islem !== null}
              title={
                bekleyenVar
                  ? "PO'nun story'ye yazdığı yanıtları şimdi oku"
                  : "Yanıt bekleyen soru yok."
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
            {v.sayim.gonderilmedi} gönderilmedi · {v.sayim.gonderildi} PO yanıtı
            bekleniyor · {v.sayim.yanitlandi} yanıtlandı
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
  const gonder = async () => {
    const y = await islem.calistir(() => api.acikSorulariGonder(tc.requirement_id));
    if (y) {
      bildir(`Açık sorular PO'ya gönderildi (${gonderilmemis.join(", ")}); yanıt gelince case'e bağlanır.`);
      tamamlandi?.();
    }
  };
  return (
    <div className="eylemler">
      <IslemDugmesi roller={["analyst"]} kucuk tur="ikincil" calisiyor={islem.calisiyor} title={GONDER_ACIKLAMASI} nedenGizli onClick={() => void gonder()}>
        Açık soruları PO'ya gönder
      </IslemDugmesi>
      {islem.hata && <AlanHatasi asistan={{ hata: islem.hata, kaynak: islem.hataNesnesi }}>{islem.hata}</AlanHatasi>}
    </div>
  );
}
