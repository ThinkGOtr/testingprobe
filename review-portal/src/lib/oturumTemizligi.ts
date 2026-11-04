// Kullanıcıya ait istemci durumunun oturum değişiminde temizlenmesi (AI-ASISTAN-PLANI §16 madde 1:
// kişi izolasyonu). Portal SPA'dır: çıkışta sayfa yeniden yüklenmez, modül düzeyindeki depolar
// (son hata, ek öneri, öneri, panel kontrolü) ve sessionStorage anahtarları aynı sekmede giriş
// yapan sonraki kullanıcıya kalırdı. Her depo kendi temizleyicisini burada kaydeder; `auth.tsx`
// çıkışta, yeni girişte ve kullanıcı değişince `oturumVerileriniTemizle()` çağırır.
//
// Bu modül hiçbir depoyu içe aktarmaz (döngü olmasın): depolar yüklenirken kendilerini kaydeder.

const temizleyiciler = new Set<() => void>();

/** Oturum değişince çağrılacak temizleyiciyi kaydeder (modül yüklenirken bir kez). */
export function oturumDegisinceTemizle(fn: () => void): () => void {
  temizleyiciler.add(fn);
  return () => {
    temizleyiciler.delete(fn);
  };
}

/** Kayıtlı bütün kullanıcı durumunu siler. Bir temizleyicinin hatası diğerlerini durdurmaz. */
export function oturumVerileriniTemizle(): void {
  temizleyiciler.forEach((fn) => {
    try {
      fn();
    } catch {
      /* yoksay */
    }
  });
}
