// Asistan içeriğinin sessionStorage anahtarları ve oturum temizliği (AI-ASISTAN-PLANI §16 madde 1: kişi
// izolasyonu). Sohbet ve ek öneri modülleri panel ilk açılınca yüklenir (kod bölme, AsistanPaneli):
// kullanıcı paneli hiç açmadan çıkış yapsa da önceki kullanıcının kayıtlı sohbeti / bekleyen ek önerisi
// sonraki kullanıcıya kalmasın diye anahtarlar ve silme kaydı ana pakettedir. Modüllerin bellek
// temizliği yine kendi kayıtlarıyla (yüklendiklerinde) yapılır.
import { oturumDegisinceTemizle } from "../../lib/oturumTemizligi";

export const SOHBET_ANAHTARI = "tp-asistan-sohbet";
export const EK_BEKLEYEN_ANAHTARI = "tp-asistan-ek-bekleyen";

oturumDegisinceTemizle(() => {
  for (const a of [SOHBET_ANAHTARI, EK_BEKLEYEN_ANAHTARI]) {
    try {
      sessionStorage.removeItem(a);
    } catch {
      /* depo kapalı */
    }
  }
});
