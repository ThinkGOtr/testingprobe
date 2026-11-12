// Asistan bağlantılarının rol süzgeci (013 inceleme turu 1, UX15).
import type { Rol } from "../../api/types";
import { OTOMASYON_ROLLERI } from "../../auth";
import { uygulamaRotasiMi } from "../../lib/rotalar";

/**
 * Portalda yalnız belli rollere açık ekranlar (App.tsx `RolGerekli` ile aynı). Asistan bu rotalara
 * yönlendirse de rolü tutmayan kullanıcıya "Git" düğmesi gösterilmez (açınca "yetkiniz yok" çıkardı).
 */
export const ROL_GEREKLI_ROTALAR: Readonly<Record<string, readonly Rol[]>> = {
  "/kod": OTOMASYON_ROLLERI,
  "/kosular": OTOMASYON_ROLLERI,
  "/demo": ["presenter"],
  "/claude-code": ["analyst"],
};

/** Rota uygulamada var ve (rol kısıtlıysa) oturumdaki role açık mı. */
export function rolRotasiAcik(rota: string, rol: Rol | null | undefined): boolean {
  if (!uygulamaRotasiMi(rota)) return false;
  const gerekli = ROL_GEREKLI_ROTALAR[rota.split(/[?#]/)[0].replace(/\/+$/, "") || "/"];
  return !gerekli || (!!rol && gerekli.includes(rol));
}
