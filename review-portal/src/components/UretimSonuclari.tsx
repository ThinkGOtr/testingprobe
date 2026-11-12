// K-T12 (011 inceleme turu 2): kod üretimi isteğinin case başına sonuçları ve dil çakışması.
//
// core `POST /code/generate` toplu yanıtında `sonuclar[]` case başına durum ve Türkçe neden taşır;
// tüm case'ler çakışırsa 409 `kod="dil_cakismasi"` döner. Başka dilde merge edilmiş testin kaldırılması
// ürün akışı değildir (backlog): ekran çıkış yolunu söyler.
import { Link } from "react-router-dom";
import { ApiError } from "../api/http";
import type { KodUretYaniti, UretimSonucu } from "../api/types";
import { Uyari } from "./ui";

/** Dil çakışmasından çıkış yolu (K-T12). */
export const DIL_CAKISMASI_CIKIS = "Mevcut test dosyasını silen bir PR'ı merge edin, sonra yeniden üretin.";

/** core yanıtındaki case durumlarının ekran adı (`basladi` listelenmez). */
export const URETIM_SONUC_ETIKETI: Record<string, string> = {
  cakisma: "Dil çakışması",
  pr_acik: "PR zaten açık",
  merge_edildi: "Zaten merge edildi",
  suruyor: "Üretim sürüyor",
  reddedildi: "Reddedildi",
  bulunamadi: "Case bulunamadı",
};

/** 409 `dil_cakismasi` mı? (kod alanı yoksa 409 + core iletisinin kalıbı.) */
export function dilCakismasiMi(e: unknown): e is ApiError {
  if (!(e instanceof ApiError)) return false;
  if (e.kod === "dil_cakismasi") return true;
  return e.status === 409 && /ile merge edildi; dil değiştirmek/.test(e.detail);
}

/** core iletisi çıkış yolunu zaten söylüyorsa yinelenmez. */
function cikisGerekli(metin: string): boolean {
  return !/silen bir PR/i.test(metin);
}

/** Üretimi başlamayan case'ler (istek sırasıyla). */
export function baslamayanlar(y: KodUretYaniti | null | undefined): UretimSonucu[] {
  return (y?.sonuclar ?? []).filter((s) => s.durum !== "basladi");
}

/**
 * Bildirim metni: core iletisi + başlamayan case sayısı (çakışma ayrıca sayılır). Ayrıntı listede durur
 * (bildirim kaybolur, liste kalır).
 */
export function uretimBildirimi(y: KodUretYaniti, varsayilan: string): string {
  const temel = y.mesaj ?? varsayilan;
  const atlanan = baslamayanlar(y);
  if (atlanan.length === 0) return temel;
  const cakisan = atlanan.filter((s) => s.durum === "cakisma").length;
  const ek = `${atlanan.length} case için üretim başlamadı${cakisan ? ` (${cakisan} dil çakışması)` : ""}; ayrıntı listede.`;
  return /başlamadı|çakış/i.test(temel) ? temel : `${temel.replace(/\.?\s*$/, ".")} ${ek}`;
}

/** 409 `dil_cakismasi`: core iletisi + çıkış yolu. */
export function DilCakismasiKutusu({ hata }: { hata: ApiError }) {
  return (
    <div data-testid="dil-cakismasi">
      <Uyari ton="hata" baslik="Kod üretilemedi: dil çakışması">
        {hata.detail}
        {cikisGerekli(hata.detail) && (
          <>
            {hata.detail.trim().endsWith(".") ? " " : ". "}
            <strong>Çıkış yolu:</strong> {DIL_CAKISMASI_CIKIS}
          </>
        )}
      </Uyari>
    </div>
  );
}

/**
 * Karışık toplu yanıtta üretimi başlamayan case'ler ve nedenleri. `caseAdi`: case kimliğinden okunur ad
 * (bilinmiyorsa kimliğin başı). Kapatılana ya da yeni istek gönderilene dek durur.
 */
export function UretimAtlananlar({
  sonuclar,
  caseAdi,
  kapat,
}: {
  sonuclar: UretimSonucu[];
  caseAdi: (id: string) => string | null;
  kapat: () => void;
}) {
  if (sonuclar.length === 0) return null;
  const cakisma = sonuclar.some((s) => s.durum === "cakisma");
  return (
    <div data-testid="uretim-atlananlar">
      <Uyari ton="uyari" baslik={`${sonuclar.length} case için üretim başlamadı`}>
        <ul className="duz-liste uretim-atlananlar kucuk">
          {sonuclar.map((s) => (
            <li key={s.case_id} data-durum={s.durum}>
              <strong>{caseAdi(s.case_id) ?? s.case_id.slice(0, 8)}</strong> — {URETIM_SONUC_ETIKETI[s.durum] ?? s.durum}
              {s.neden && `: ${s.neden}`}
              {s.script_id && (
                <>
                  {" · "}
                  <Link to={`/kod/${encodeURIComponent(s.script_id)}`}>Mevcut script</Link>
                </>
              )}
            </li>
          ))}
        </ul>
        {cakisma && (
          <p className="kucuk">
            <strong>Dil çakışmasından çıkış:</strong> {DIL_CAKISMASI_CIKIS}
          </p>
        )}
        <p className="kucuk">
          <button type="button" className="dugme-metin" onClick={kapat}>
            Listeyi kapat
          </button>
        </p>
      </Uyari>
    </div>
  );
}
