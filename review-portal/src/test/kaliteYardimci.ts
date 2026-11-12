// 012 tur 2 test yardımcıları: örnek veride T2 (minimum sipariş) AI taslağı `<= 750` ile PO onayı bekler.
// Demo hikâyesi (u2 N2): PO değişiklik ister → analist `< 750` yapar → gönderir → PO onaylar.
import { api } from "../api/client";
import { bekleyenMockIs } from "../api/mock/handlers";
import { MIN_SIPARIS_DOGRU } from "../api/mock/kaliteVerisi";
import type { KararTablosu, KararTablosuIcerik } from "../api/types";
import { oturumAc } from "./yardimci";

const REQ = "req-tpd-1";
const t2 = async (): Promise<KararTablosu> => (await api.kararTablolari(REQ)).tablolar.find((t) => /Minimum/.test(t.icerik.ad) && t.durum !== "superseded")!;

export async function isleriBekle(): Promise<void> {
  for (let i = 0; i < 400 && bekleyenMockIs() > 0; i++) await new Promise((r) => setTimeout(r, 5));
}

/** T2'yi analistin düzenleyebileceği taslağa döndürür (analist "Geri çek"); oturum analist kalır. */
export async function t2Taslak(): Promise<KararTablosu> {
  await oturumAc("analist");
  const t = await t2();
  if (t.durum === "pending_po") return api.kararTablosuGecis(t.id, "withdraw");
  return t;
}

/** Demo adımı 2: PO değişiklik ister, analist `< 750` yapıp gönderir (T2 yeniden PO onayı bekler). */
export async function t2Duzelt(icerik: KararTablosuIcerik = MIN_SIPARIS_DOGRU): Promise<KararTablosu> {
  await oturumAc("analist");
  let t = await t2();
  if (t.durum === "pending_po") {
    await oturumAc("po");
    t = await api.kararTablosuGecis(t.id, "request-changes", { icerik_hash: t.icerik_hash, gerekce: "AC3 'altında' diyor; tam 750,00 TL'de uyarı olmamalı." });
  }
  await oturumAc("analist");
  t = await api.kararTablosuKaydet(t.id, { icerik, icerik_hash: t.icerik_hash });
  return api.kararTablosuGecis(t.id, "submit", { icerik_hash: t.icerik_hash });
}

/**
 * T2'yi PO'ya onaylatır. `duzelt` (varsayılan): önce `< 750` düzeltmesi (C6'daki AI sınır hatası uyumsuz olur);
 * `duzelt: false`: AI'ın `<= 750` taslağı olduğu gibi onaylanır (C6 da "uyumlu" görünür). Oturum analist kalır.
 */
export async function t2Onayla({ duzelt = true, bekle = true }: { duzelt?: boolean; bekle?: boolean } = {}): Promise<KararTablosu> {
  await oturumAc("analist");
  let t = duzelt ? await t2Duzelt() : await t2();
  await oturumAc("po");
  t = await api.kararTablosuGecis(t.id, "approve", { icerik_hash: t.icerik_hash });
  if (bekle) await isleriBekle();
  await oturumAc("analist");
  return t;
}
