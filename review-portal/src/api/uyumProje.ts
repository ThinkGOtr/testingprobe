// Çok proje (TP-COK-PROJE-PLANI §6.2–6.3): `GET /api/projeler` yanıtını portal biçimine çevirir.
//
// Sözleşme (Şerit 2 ve ortak değiştirici 1.1.0 ile aynı biçim):
//   {enabled: true, projects: [{pid, name, org_name, roles: [TP rol kodu]}], active: {pid},
//    role_labels: {kod: {tr, en}}}
// Geriye/ileriye dönük hoşgörü: `activeId`/`active_id`/`secili`, `id`, `ad`/`org_ad`/`roller` ve
// `projeler` dizisi ya da çıplak dizi de kabul edilir. `enabled: false` → null (seçici yok).
import type { ProjeListesi, ProjeOzeti } from "./types";
import { nesneMi } from "./uyum";

function metin(v: unknown): string {
  return typeof v === "string" ? v.trim() : typeof v === "number" ? String(v) : "";
}

function projeUyarla(h: unknown): ProjeOzeti | null {
  if (!nesneMi(h)) return null;
  const pid = metin(h.pid ?? h.id);
  if (!pid) return null;
  const ad = metin(h.name ?? h.ad) || metin(h.kod ?? h.code) || pid;
  const org = metin(h.org_name ?? h.org_ad ?? h.org);
  const kod = metin(h.kod ?? h.code);
  const hamRoller = Array.isArray(h.roles) ? h.roles : Array.isArray(h.roller) ? h.roller : [];
  return { pid, ad, kod: kod || null, org_ad: org || null, roller: hamRoller.filter((r): r is string => typeof r === "string") };
}

export function projeListesiUyarla(ham: unknown): ProjeListesi | null {
  if (Array.isArray(ham)) ham = { projects: ham };
  if (!nesneMi(ham) || ham.enabled === false) return null;
  const dizi = Array.isArray(ham.projects) ? ham.projects : Array.isArray(ham.projeler) ? ham.projeler : [];
  const projeler = dizi.map(projeUyarla).filter((p): p is ProjeOzeti => p !== null);
  const aktif = ham.active ?? ham.activeId ?? ham.active_id ?? ham.secili;
  const aktifPid = nesneMi(aktif) ? metin(aktif.pid ?? aktif.id) : metin(aktif);
  const etiketler = ham.role_labels ?? ham.roleLabels;
  return {
    projeler,
    secili: projeler.some((p) => p.pid === aktifPid) ? aktifPid : null,
    ...(nesneMi(etiketler) ? { rolEtiketleri: etiketler as ProjeListesi["rolEtiketleri"] } : {}),
  };
}
