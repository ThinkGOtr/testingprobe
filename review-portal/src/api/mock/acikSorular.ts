// Örnek veri: açık soru döngüsü (specs/011 K16; D6) — core `features/cases/acik_sorular.py` ile
// aynı biçim.
//   GET  /requirements/{id}/open-questions          → güncel setin soruları + PO durumu/yanıtı
//   POST /requirements/{id}/open-questions/send     → {varsayimlar?}; analist; Jira story'si gerekir
//   POST /requirements/{id}/open-questions/refresh  → analist; PO yanıtlarını okur
// Örnek veride Jira yoktur: gönderim yalnız kayda geçer; "yanıtları oku" gönderilmiş sorulara
// "(örnek veri)" işaretli sabit bir PO yanıtı yazar.
import { ApiError } from "../http";
import type {
  AcikSoruDurumu,
  AcikSoruKaydi,
  AcikSorularYaniti,
} from "../acikSoruTipleri";
import type { GereksinimDetay, Kullanici, Rol, TestCase } from "../types";
import { birlesikOzet } from "./caseV3";
import type { MockVeri } from "./fixtures";

type Rota = [
  string,
  RegExp,
  (m: RegExpMatchArray, q: URLSearchParams, govde: unknown) => unknown,
];

/** Gönderilmiş soru kaydı (core `acik_soru` satırı). */
export interface MockAcikSoru {
  tur: "soru" | "varsayim";
  metin: string;
  etiket: string;
  kaynak_id: string;
  sahip: string;
  durum: "gonderildi" | "yanitlandi";
  gonderen: string;
  gonderim_zamani: string;
  yanit: string | null;
  yanit_yazari: string | null;
  yanit_zamani: string | null;
}

export interface AcikSoruBaglami {
  veri: () => MockVeri;
  girisGerekli: () => Kullanici;
  rolGerekli: (...roller: Rol[]) => Kullanici;
  gereksinim: (id: string) => GereksinimDetay;
  kaydet: () => void;
  denetimEkle: (
    eylem: string,
    nesne: string,
    ozet: string,
    aktor?: string,
  ) => void;
}

export const ONERI_MESAJI =
  "PO yanıtladı: beklenen sonucu yanıta göre yazıp atfı kaldırarak case'i düzeltin (hazır yapın) ya da yanıtı kaynak alarak yeniden üretin.";
export const ORNEK_PO_YANITI =
  "(örnek veri) PO yanıtı: kural story'ye eklendi; beklenen sonucu buna göre yazın.";
export const GONDERILECEK_YOK =
  "Gönderilecek açık soru yok: güncel case setindeki sorular zaten gönderildi ya da yanıtlandı.";
export const STORY_YOK_ENGELI =
  "Gereksinimin Jira story'si yok; açık sorular PO'ya story yorumu olarak gönderilir.";

const normal = (m: string) =>
  m.split(/\s+/).filter(Boolean).join(" ").toLocaleLowerCase("tr");
const simdi = () => new Date().toISOString();

interface Kalem {
  tur: "soru" | "varsayim";
  kaynak_id: string;
  metin: string;
  sahip: string;
  caseler: TestCase[];
}

function guncelCaseler(v: MockVeri, rid: string): TestCase[] {
  return v.caseler
    .filter(
      (c) =>
        c.requirement_id === rid &&
        c.durum !== "superseded" &&
        c.durum !== "rejected",
    )
    .sort((a, b) => a.sira_no - b.sira_no);
}

function kalemler(v: MockVeri, rid: string): Kalem[] {
  const ozet = birlesikOzet(v.caseUretimleri?.[rid]);
  if (!ozet) return [];
  const caseler = guncelCaseler(v, rid);
  const out: Kalem[] = [];
  const gorulen = new Set<string>();
  for (const q of ozet.open_questions) {
    if (gorulen.has(`soru:${normal(q.question)}`)) continue;
    gorulen.add(`soru:${normal(q.question)}`);
    out.push({
      tur: "soru",
      kaynak_id: q.id,
      metin: q.question,
      sahip: q.owner,
      caseler: caseler.filter((c) =>
        (c.icerik.open_question_refs ?? []).includes(q.id),
      ),
    });
  }
  for (const a of ozet.assumptions) {
    if (gorulen.has(`varsayim:${normal(a.statement)}`)) continue;
    gorulen.add(`varsayim:${normal(a.statement)}`);
    const dayanan = caseler.filter((c) =>
      (c.icerik.assumption_refs ?? []).includes(a.id),
    );
    if (dayanan.length)
      out.push({
        tur: "varsayim",
        kaynak_id: a.id,
        metin: a.statement,
        sahip: a.owner,
        caseler: dayanan,
      });
  }
  return out;
}

function kayitlar(v: MockVeri, rid: string): MockAcikSoru[] {
  return ((v.acikSorular ??= {})[rid] ??= []);
}

function kayitBul(
  v: MockVeri,
  rid: string,
  tur: "soru" | "varsayim",
  metin: string,
): MockAcikSoru | undefined {
  return kayitlar(v, rid).find(
    (k) => k.tur === tur && normal(k.metin) === normal(metin),
  );
}

function oneri(k: MockAcikSoru | undefined, caseler: TestCase[]) {
  const bekleyen = caseler.filter((c) => c.durum === "draft");
  if (!k || k.durum !== "yanitlandi" || bekleyen.length === 0) return null;
  return {
    eylem: "duzelt_veya_yeniden_uret" as const,
    case_ids: bekleyen.map((c) => c.id),
    mesaj: ONERI_MESAJI,
  };
}

/** core `view` biçimi. */
export function acikSorularYaniti(
  v: MockVeri,
  g: GereksinimDetay,
): AcikSorularYaniti {
  const sorular: AcikSoruKaydi[] = kalemler(v, g.id).map((k) => {
    const kayit = kayitBul(v, g.id, k.tur, k.metin);
    return {
      etiket: kayit?.etiket ?? null,
      kaynak_id: k.kaynak_id,
      tur: k.tur,
      metin: k.metin,
      sahip: k.sahip,
      durum: kayit?.durum ?? "gonderilmedi",
      gonderim: kayit
        ? {
            zaman: kayit.gonderim_zamani,
            gonderen: kayit.gonderen,
            jira_comment_id: null,
          }
        : null,
      yanit:
        kayit?.durum === "yanitlandi"
          ? {
              metin: kayit.yanit ?? "",
              yazar: kayit.yanit_yazari,
              zaman: kayit.yanit_zamani,
            }
          : null,
      bekleyen_caseler: k.caseler.map((c) => ({
        id: c.id,
        sira_no: c.sira_no,
        uretim_no: c.uretim_no ?? 1,
        title: c.icerik.title,
        durum: c.durum,
        readiness: c.icerik.readiness ?? "ready",
      })),
      oneri: oneri(kayit, k.caseler),
    };
  });
  const sayim: Record<AcikSoruDurumu, number> = {
    gonderilmedi: 0,
    gonderildi: 0,
    yanitlandi: 0,
  };
  for (const s of sorular) sayim[s.durum] += 1;
  const engel = !g.jira_key
    ? STORY_YOK_ENGELI
    : sayim.gonderilmedi === 0
      ? "Gönderilmemiş açık soru yok."
      : null;
  return {
    requirement_id: g.id,
    jira_key: g.jira_key,
    sayim,
    gonderilebilir: engel === null,
    gonderim_engeli: engel,
    sorular,
  };
}

function gonder(
  b: AcikSoruBaglami,
  rid: string,
  govde: unknown,
): AcikSorularYaniti {
  const k = b.rolGerekli("analyst");
  const g = b.gereksinim(rid);
  if (!g.jira_key) throw new ApiError(409, STORY_YOK_ENGELI);
  const varsayimlar =
    typeof govde === "object" &&
    govde !== null &&
    (govde as { varsayimlar?: unknown }).varsayimlar === true;
  const v = b.veri();
  const liste = kayitlar(v, rid);
  const sonraki = (onek: string) =>
    Math.max(
      0,
      ...liste
        .filter((x) => x.etiket.startsWith(onek))
        .map((x) => Number(x.etiket.slice(2)) || 0),
    ) + 1;
  const gidecek = kalemler(v, rid).filter(
    (x) =>
      (varsayimlar || x.tur === "soru") && !kayitBul(v, rid, x.tur, x.metin),
  );
  if (gidecek.length === 0) throw new ApiError(409, GONDERILECEK_YOK);
  const zaman = simdi();
  for (const x of gidecek) {
    liste.push({
      tur: x.tur,
      metin: x.metin,
      etiket: `${x.tur === "soru" ? "CQ" : "CA"}${sonraki(x.tur === "soru" ? "CQ" : "CA")}`,
      kaynak_id: x.kaynak_id,
      sahip: x.sahip,
      durum: "gonderildi",
      gonderen: k.kullanici_adi,
      gonderim_zamani: zaman,
      yanit: null,
      yanit_yazari: null,
      yanit_zamani: null,
    });
  }
  b.denetimEkle(
    "acik_soru.gonderildi",
    `requirement:${rid}`,
    `${gidecek.length} soru PO'ya gönderildi (${g.jira_key})`,
  );
  b.kaydet();
  return acikSorularYaniti(v, g);
}

function yanitlariOku(b: AcikSoruBaglami, rid: string): AcikSorularYaniti {
  b.rolGerekli("analyst");
  const g = b.gereksinim(rid);
  const v = b.veri();
  for (const k of kayitlar(v, rid)) {
    if (k.durum !== "gonderildi") continue;
    Object.assign(k, {
      durum: "yanitlandi",
      yanit: ORNEK_PO_YANITI,
      yanit_yazari: "po",
      yanit_zamani: simdi(),
    });
    b.denetimEkle(
      "acik_soru.yanitlandi",
      `requirement:${rid}`,
      `${k.etiket} yanıtlandı`,
      "system",
    );
  }
  b.kaydet();
  return acikSorularYaniti(v, g);
}

export function acikSoruRotalari(b: AcikSoruBaglami): Rota[] {
  return [
    [
      "GET",
      /^\/requirements\/([^/]+)\/open-questions$/,
      (m) => {
        b.girisGerekli();
        return acikSorularYaniti(
          b.veri(),
          b.gereksinim(decodeURIComponent(m[1])),
        );
      },
    ],
    [
      "POST",
      /^\/requirements\/([^/]+)\/open-questions\/send$/,
      (m, _q, g) => gonder(b, decodeURIComponent(m[1]), g),
    ],
    [
      "POST",
      /^\/requirements\/([^/]+)\/open-questions\/refresh$/,
      (m) => yanitlariOku(b, decodeURIComponent(m[1])),
    ],
  ];
}

/** core `case_fields`: atıf kimliği → PO durumu (`po_sorulari`) + öneri; mevcut alanlar değişmez. */
export function caseAcikSoruAlanlari(
  v: MockVeri,
  c: TestCase,
): {
  po_sorulari: Record<string, unknown>;
  po_yanit_onerisi: TestCase["po_yanit_onerisi"];
} {
  const yanitli: string[] = [];
  const po_sorulari: Record<string, unknown> = {};
  const ekle = (tur: "soru" | "varsayim", id: string, metin: string) => {
    const k = kayitBul(v, c.requirement_id, tur, metin);
    if (k?.durum === "yanitlandi") yanitli.push(k.etiket);
    po_sorulari[id] = {
      tur,
      po_etiketi: k?.etiket ?? null,
      po_durumu: k?.durum ?? "gonderilmedi",
      po_yaniti:
        k?.durum === "yanitlandi"
          ? {
              metin: k.yanit ?? "",
              yazar: k.yanit_yazari,
              zaman: k.yanit_zamani,
            }
          : null,
    };
  };
  for (const q of c.acik_sorular ?? []) ekle("soru", q.id, q.question);
  for (const a of c.varsayimlar ?? []) ekle("varsayim", a.id, a.statement);
  return {
    po_sorulari,
    po_yanit_onerisi:
      yanitli.length && c.durum === "draft" && !c.legacy
        ? {
            eylem: "duzelt_veya_yeniden_uret",
            etiketler: yanitli,
            mesaj: ONERI_MESAJI,
          }
        : null,
  };
}

/** core `record_correction_source`: düzeltme yanıtlanan soru atfını kaldırıp case'i hazır yaptıysa. */
export function duzeltmeKaynagi(
  b: AcikSoruBaglami,
  c: TestCase,
  yeni: TestCase["icerik"],
): void {
  if ((yeni.readiness ?? "ready") !== "ready" || !c.icerik.readiness) return;
  const ozet = birlesikOzet(b.veri().caseUretimleri?.[c.requirement_id]);
  if (!ozet) return;
  const etiketler: string[] = [];
  for (const ref of c.icerik.open_question_refs ?? []) {
    if ((yeni.open_question_refs ?? []).includes(ref)) continue;
    const q = ozet.open_questions.find((x) => x.id === ref);
    const k = q && kayitBul(b.veri(), c.requirement_id, "soru", q.question);
    if (k?.durum === "yanitlandi") etiketler.push(k.etiket);
  }
  for (const ref of c.icerik.assumption_refs ?? []) {
    if ((yeni.assumption_refs ?? []).includes(ref)) continue;
    const a = ozet.assumptions.find((x) => x.id === ref);
    const k =
      a && kayitBul(b.veri(), c.requirement_id, "varsayim", a.statement);
    if (k?.durum === "yanitlandi") etiketler.push(k.etiket);
  }
  if (etiketler.length)
    b.denetimEkle(
      "case.po_yaniti_kaynak",
      `test_case:${c.id}`,
      `kaynak: PO yanıtı ${etiketler.join(", ")}`,
    );
}
