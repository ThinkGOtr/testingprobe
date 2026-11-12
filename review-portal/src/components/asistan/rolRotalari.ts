// Asistan bağlantılarının rol süzgeci (013 inceleme turu 1, UX15; 012 izin kataloğu).
import type { Rol } from "../../api/types";
import { izinVar, rolIzinleri, rotaIzinleri } from "../../lib/yetki";
import { uygulamaRotasiMi } from "../../lib/rotalar";

/**
 * Rota uygulamada var ve oturumdaki rol açabiliyor mu. Sayfa koruması ile aynı tablo
 * (`ROTA_IZINLERI`, ANALIZ 012 §4.2): asistan izinsiz ekrana yönlendirse de "Git" düğmesi
 * gösterilmez (açınca "yetkiniz yok" çıkardı). Korumasız rota herkese açıktır.
 */
export function rolRotasiAcik(rota: string, rol: Rol | null | undefined): boolean {
  if (!uygulamaRotasiMi(rota)) return false;
  const istenen = rotaIzinleri(rota);
  if (istenen.length === 0) return true;
  return !!rol && izinVar(new Set(rolIzinleri(rol)), ...istenen);
}
