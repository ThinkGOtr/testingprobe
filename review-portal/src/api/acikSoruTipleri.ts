// Açık soru döngüsü (specs/011 K16; D6): core `GET/POST /requirements/{id}/open-questions*`.
// Soru, case üretiminin birleşik özetindeki açık soru (`CQn`) ya da doğrulama istenen varsayımdır
// (`CAn`); PO'ya story yorumu olarak gider, PO'nun `CQn: …` yanıtı geri okunur.
import type { CaseDurumu, CaseHazirlik } from "./types";
import type { Ton } from "../lib/etiketler";

export type AcikSoruDurumu = "gonderilmedi" | "gonderildi" | "yanitlandi";

export const ACIK_SORU_DURUMU: Record<
  AcikSoruDurumu,
  { etiket: string; ton: Ton; aciklama: string }
> = {
  gonderilmedi: {
    etiket: "PO'ya gönderilmedi",
    ton: "notr",
    aciklama: "Soru henüz story'ye yorum olarak yazılmadı.",
  },
  gonderildi: {
    etiket: "PO yanıtı bekleniyor",
    ton: "uyari",
    aciklama: "Soru story'ye yorum olarak yazıldı; PO yanıtı bekleniyor.",
  },
  yanitlandi: {
    etiket: "Yanıtlandı",
    ton: "basari",
    aciklama:
      "PO soruyu kimliğiyle yanıtladı; yanıt case'in beklenen sonucunun kaynağıdır.",
  },
};

/** PO'nun Jira yorumundaki yanıtı (güvenilmeyen düz metin). */
export interface PoYaniti {
  metin: string;
  yazar: string | null;
  zaman: string | null;
  jira_comment_id?: string | null;
}

export interface AcikSoruBekleyenCase {
  id: string;
  sira_no: number;
  uretim_no: number;
  title: string;
  durum: CaseDurumu;
  readiness: CaseHazirlik;
}

/** Yanıtlanan soruya bağlı taslak case için öneri. */
export interface AcikSoruOnerisi {
  eylem: "duzelt_veya_yeniden_uret";
  mesaj: string;
  case_ids?: string[];
  etiketler?: string[];
}

export interface AcikSoruKaydi {
  /** PO'nun yanıtta kullandığı kimlik (CQ1 / CA1); gönderilmeden önce null. */
  etiket: string | null;
  /** Birleşik özetteki kimlik (Q1 / A1). */
  kaynak_id: string;
  tur: "soru" | "varsayim";
  metin: string;
  /** PO | analyst | developer | "" */
  sahip: string;
  durum: AcikSoruDurumu;
  gonderim: {
    zaman: string | null;
    gonderen: string;
    jira_comment_id: string | null;
  } | null;
  yanit: PoYaniti | null;
  /** Gönderim yarıda kaldı (Jira hatası/zaman aşımı); yorum yazılmış olabilir. */
  gonderim_belirsiz?: boolean;
  bekleyen_caseler: AcikSoruBekleyenCase[];
  oneri: AcikSoruOnerisi | null;
}

export interface AcikSorularYaniti {
  requirement_id: string;
  jira_key: string | null;
  sayim: Record<AcikSoruDurumu, number>;
  gonderilebilir: boolean;
  gonderim_engeli: string | null;
  sorular: AcikSoruKaydi[];
}
