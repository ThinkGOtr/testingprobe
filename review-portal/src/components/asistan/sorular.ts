// Boş sohbette soru önerileri (AI-ASISTAN-PLANI §11): rol + rota birlikte. `modelsiz` öneriler
// hata sözlüğü ya da kayıt şablonuyla cevaplanır; canlı model kapalıyken yalnız bunlar gösterilir.
import type { Rol } from "../../api/types";
import type { EkranBaglami } from "../../lib/ekranBaglami";

export interface SoruOnerisi {
  metin: string;
  modelsiz: boolean;
}

const ROL_SORULARI: Record<Rol, SoruOnerisi[]> = {
  analyst: [{ metin: "Onay bekleyen story'ler hangileri?", modelsiz: false }],
  po: [{ metin: "Onay bekleyen story'ler hangileri?", modelsiz: false }],
  engineer: [{ metin: "Son koşu neden düştü?", modelsiz: false }],
  tester: [{ metin: "Flaky test nasıl ayıklanır?", modelsiz: false }],
  presenter: [{ metin: "Son gece koşusunda kaç test kırıldı, neden?", modelsiz: false }],
};

const EKRAN_SORULARI: Record<string, SoruOnerisi[]> = {
  "/gereksinimler/:id": [{ metin: "Bu gereksinim neden bekliyor?", modelsiz: false }],
  "/gereksinimler/:id/caseler": [{ metin: "Bu case'i onaylamadan önce neye bakmalıyım?", modelsiz: false }],
  "/kod/:id": [{ metin: "Kırarak doğrulama ne işe yarar?", modelsiz: false }],
  "/kosular/:id": [{ metin: "Bu koşu neden düştü?", modelsiz: false }],
  "/hatalar/:id": [{ metin: "Bu hata sınıfı ne demek?", modelsiz: false }],
};

export function soruOnerileri(rol: Rol | undefined, ekran: EkranBaglami, opts: { modelAcik: boolean; sonHataVar: boolean }): SoruOnerisi[] {
  const liste: SoruOnerisi[] = [{ metin: "Bugün ne yapmalıyım?", modelsiz: true }];
  if (opts.sonHataVar) liste.unshift({ metin: "Az önceki hata ne demek?", modelsiz: true });
  const anahtar = ekran.varlik?.anahtar;
  if (anahtar && ekran.varlik?.tur === "requirement") liste.push({ metin: `${anahtar} neden bekliyor?`, modelsiz: true });
  else if (ekran.rota_kalibi) liste.push(...(EKRAN_SORULARI[ekran.rota_kalibi] ?? []));
  if (rol) liste.push(...ROL_SORULARI[rol]);
  liste.push({ metin: "Bu ekranda ne yapabilirim?", modelsiz: false });
  const tekil = liste.filter((s, i) => liste.findIndex((x) => x.metin === s.metin) === i);
  return (opts.modelAcik ? tekil : tekil.filter((s) => s.modelsiz)).slice(0, 5);
}
