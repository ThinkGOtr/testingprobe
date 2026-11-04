// Kule maliyet gösteriminin ortak kuralı (TASARIM-YENILEME-PLANI K5; anayasa: ölçülmemiş sayı söylenmez).
// Tüm AI çağrıları REPLAY'den karşılandıysa ücret ölçülmez: "$0,00" ölçüm gibi okunmasın.
// null koruması: çağrı sayısı bilinmiyorsa REPLAY sayılmaz (yolHaritasi.ts modOzeti ile aynı mantık).
export function tumuReplayMi(ai: { cagri_sayisi: number | null; replay_cagri: number | null } | null | undefined): boolean {
  if (!ai) return false;
  return ai.cagri_sayisi != null && ai.cagri_sayisi > 0 && ai.replay_cagri === ai.cagri_sayisi;
}
