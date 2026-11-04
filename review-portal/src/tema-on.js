/*
 * İlk boyamadan önce kayıtlı temayı uygular (klasik, senkron betik; modül değil).
 *
 * index.html `data-theme="dark"` ile gelir; asıl uygulama (main.tsx → temaUygula(temaOku())) paket indirilip
 * çalışınca devreye girer. Bu betik olmadan açık ya da "sistem" (açık işletim sistemi) seçen kullanıcı her soğuk
 * açılışta önce koyu zemin görürdü. vite.config.ts'teki `tp-tema-on` eklentisi bu dosyayı derlemede
 * küçültüp `assets/tema-on-[hash].js` olarak çıkarır ve `<head>`in sonuna (stil bağlantısından sonra, gövdeden
 * önce) klasik `<script src>` ile ekler: gövde boyanmadan çalışır. Aynı kökenli dosya, CSP `default-src 'self'`
 * yeterli, satır içi betik yok. Dosya src/ altında (Dockerfile yalnız src/ kopyalar).
 *
 * Kurallar src/lib/tema.ts ile aynı (bağ: src/lib/tema.test.tsx "tema-on.js" testleri): `tp-tema-v=2` işareti
 * yoksa kayıt yok sayılır (göçü ve yazmayı temaOku yapar; bu betik depolamaya yazmaz); koyu → dark,
 * açık → light, sistem → öznitelik yok; tanınmayan değer ya da depolama hatası → index.html'deki koyu kalır.
 */
(function () {
  try {
    var depo = window.localStorage;
    if (depo.getItem("tp-tema-v") !== "2") return;
    var t = depo.getItem("tp-tema");
    var kok = document.documentElement;
    if (t === "acik") kok.setAttribute("data-theme", "light");
    else if (t === "sistem") kok.removeAttribute("data-theme");
    else if (t === "koyu") kok.setAttribute("data-theme", "dark");
  } catch (e) {
    /* depolama yok ya da erişim engelli: koyu kalır */
  }
})();
