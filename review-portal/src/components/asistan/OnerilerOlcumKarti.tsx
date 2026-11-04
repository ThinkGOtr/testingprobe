// Kontrol Kulesi "Öneriler" kartı (AI-ASISTAN-PLANI §17.7) ve asistan maliyet grubu (§6.4 son madde).
// Kural başına "Neden? Sor" ve Faydalı / Gizle / Yaptım sayıları; kişi bazlı rapor yok, gösterim
// sayısı tutulmaz (istemci izleme yok). Veri `GET /control-tower` yanıtının `asistan` bölümünden gelir;
// eski core bu bölümü vermezse kart çizilmez (uydurulmaz). Sayılar asistan saklama süresiyle
// (`saklama_gun`) sınırlıdır; maliyet `ai_call`'dan tüm zamanlardır (saklama temizliğine girmez).
// Maliyet K5'e uyar (ölçülmemiş sayı söylenmez): diğer AI işleri AI katkısı kartıyla aynı kuralla
// REPLAY'de "REPLAY — ölçülmedi"; asistanın hiç model çağrısı yoksa "$0,00" yerine "çağrı yok";
// maliyet verilmediyse (null) "ölçülmedi".
import { KaynakIpucu } from "../KaynakIpucu";
import type { ReactNode } from "react";
import type { KontrolKulesi } from "../../api/types";
import { BosDurum, Cip, Kart, Metrik, Olculmedi } from "../ui";
import { dolar } from "../../lib/format";
import { tumuReplayMi } from "../../lib/aiMaliyet";

export interface MaliyetGrubu {
  cagri: number;
  /** null: core maliyeti bildirmedi (ölçülmedi; 0 uydurulmaz). */
  maliyet_usd: number | null;
  maliyet_usd_bugun: number | null;
  amaclar: string[];
}

export interface OneriOlcumSatiri {
  kural_id: string;
  baslik: string | null;
  ekran: string | null;
  /** Kural dosyasından kaldırılmış ama kaydı kalan kimlik → false. */
  kural_setinde: boolean;
  neden_sor: number;
  faydali: number;
  gizle: number;
  yaptim: number;
}

export interface AsistanKuleOlcumu {
  maliyet: { asistan: MaliyetGrubu; diger: MaliyetGrubu };
  oneriler: OneriOlcumSatiri[];
  oneri_toplam: { neden_sor: number; faydali: number; gizle: number; yaptim: number };
  saklama_gun: number;
}

/** Kontrol Kulesi yanıtının bu kartın okuduğu parçası (tip `api/types`'a dokunmadan). */
export interface AsistanliKule {
  asistan?: AsistanKuleOlcumu | null;
  /** Diğer AI işlerinin REPLAY durumu AI katkısı kartıyla aynı kaynaktan okunur (K5). */
  ai_katkisi?: Pick<KontrolKulesi["ai_katkisi"], "cagri_sayisi" | "replay_cagri"> | null;
  kaynaklar?: Partial<Record<string, string>>;
}

const SUTUNLAR = [
  { anahtar: "neden_sor", ad: "Neden? Sor" },
  { anahtar: "faydali", ad: "Faydalı" },
  { anahtar: "gizle", ad: "Gizle" },
  { anahtar: "yaptim", ad: "Yaptım" },
] as const;

function etkilesim(s: OneriOlcumSatiri): number {
  return s.neden_sor + s.faydali + s.gizle + s.yaptim;
}

/** Asistan maliyeti: çağrı yoksa sıfır "ölçüm" gibi okunmasın; null → ölçülmedi. */
function asistanMaliyeti(g: MaliyetGrubu, deger: number | null): ReactNode {
  if (g.cagri === 0) return <Olculmedi metin="çağrı yok" />;
  return deger === null ? <Olculmedi /> : dolar(deger);
}

export function OnerilerOlcumKarti({ kule }: { kule: AsistanliKule }) {
  const o = kule.asistan;
  if (!o) return null;
  const etkilesimli = o.oneriler.filter((s) => etkilesim(s) > 0);
  const sessiz = o.oneriler.length - etkilesimli.length;
  const as = o.maliyet.asistan;
  // Alt satır cümle içidir: ölçülmedi hap değil düz metin (değer yuvalarındaki hap AI katkısı kartıyla aynı).
  const digerBugun = tumuReplayMi(kule.ai_katkisi)
    ? "REPLAY — ölçülmedi"
    : o.maliyet.diger.maliyet_usd_bugun === null
      ? "ölçülmedi"
      : dolar(o.maliyet.diger.maliyet_usd_bugun);

  return (
    <Kart
      baslik="Öneriler ve asistan"
      className="kule-oneriler"
      eylemler={<KaynakIpucu kaynak={kule.kaynaklar?.asistan} testId="oneri-olcum-kaynak" />}
    >
      <div className="metrik-izgara">
        <Metrik
          etiket="Asistan maliyeti (toplam)"
          deger={<span data-testid="asistan-maliyet">{asistanMaliyeti(as, as.maliyet_usd)}</span>}
          alt={`${as.cagri} model çağrısı${as.amaclar.length ? ` · ${as.amaclar.join(", ")}` : ""}`}
        />
        <Metrik
          etiket="Asistan bugün"
          deger={<span data-testid="asistan-maliyet-bugun">{asistanMaliyeti(as, as.maliyet_usd_bugun)}</span>}
          alt={<span data-testid="diger-ai-bugun">Diğer AI işleri bugün: {digerBugun}</span>}
        />
        <Metrik etiket="Neden? Sor" deger={<span data-testid="oneri-toplam-neden">{o.oneri_toplam.neden_sor}</span>} />
        <Metrik
          etiket="Faydalı / Gizle / Yaptım"
          deger={
            <span data-testid="oneri-toplam-geri-bildirim">
              {o.oneri_toplam.faydali} / {o.oneri_toplam.gizle} / {o.oneri_toplam.yaptim}
            </span>
          }
        />
      </div>

      {etkilesimli.length === 0 ? (
        <BosDurum baslik="Henüz öneri etkileşimi yok.">
          Kural başına sayılar, öneri kartlarında “Neden? Sor”, “Faydalı”, “Gizle” ya da “Yaptım” kullanıldıkça burada görünür.
        </BosDurum>
      ) : (
        <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Öneri kuralı ölçümleri">
          <table className="tablo tablo-sik" data-testid="oneri-olcum-tablosu">
            <thead>
              <tr>
                <th scope="col">Kural</th>
                {SUTUNLAR.map((s) => (
                  <th key={s.anahtar} scope="col" className="sayi">
                    {s.ad}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {etkilesimli.map((s) => (
                <tr key={s.kural_id}>
                  <td>
                    <strong>{s.baslik ?? s.kural_id}</strong>
                    <br />
                    <span className="kucuk soluk">
                      <code>{s.kural_id}</code>
                      {s.ekran ? ` · ${s.ekran}` : ""}
                    </span>{" "}
                    {!s.kural_setinde && (
                      <Cip ton="uyari" title="Bu kural artık kural dosyasında yok; kayıtlı sayıları gösteriliyor.">
                        kaldırıldı
                      </Cip>
                    )}
                  </td>
                  {SUTUNLAR.map((c) => (
                    <td key={c.anahtar} className="sayi">
                      {s[c.anahtar]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="kucuk soluk">
        Son {o.saklama_gun} gün · kural başına toplam; kişi bazlı rapor ve gösterim sayısı tutulmaz.
        {sessiz > 0 ? ` ${sessiz} kuralda henüz etkileşim yok.` : ""}
      </p>
    </Kart>
  );
}
