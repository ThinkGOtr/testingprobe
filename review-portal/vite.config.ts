import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Üretim derlemesinde Inter'in latin ve latin-ext (ğ ş ı İ) woff2 dosyalarını `<link rel="preload">` ile
 * erken ister: fontlar CSS ayrıştırılmadan başlar, ilk boyamadaki yedek font → Inter kayması kısalır.
 * Dosyalar hashli ve aynı kökenlidir (CSP `default-src 'self'` yeterli; satır içi betik yok). Font istekleri
 * CORS kipinde yapıldığından `crossorigin` zorunludur (yoksa tarayıcı dosyayı iki kez indirir).
 * Her sayfa Türkçe metin taşıdığı için iki dosya da her açılışta kullanılır; JetBrains Mono ve diğer alt
 * kümeler önyüklenmez. Geliştirme sunucusunda (paket yok) hiçbir şey eklenmez.
 */
function fontOnyukleme(): Plugin {
  let base = "/";
  return {
    name: "tp-font-onyukleme",
    apply: "build",
    configResolved(c) {
      base = c.base;
    },
    transformIndexHtml: {
      order: "post",
      handler(_html, ctx) {
        if (!ctx.bundle) return [];
        return Object.keys(ctx.bundle)
          .filter((dosya) => /\/inter-latin(-ext)?-wght-normal-[\w-]+\.woff2$/.test(dosya))
          .sort()
          .map((dosya) => ({
            tag: "link",
            attrs: { rel: "preload", href: base + dosya, as: "font", type: "font/woff2", crossorigin: "" },
            injectTo: "head" as const,
          }));
      },
    },
  };
}

// Geliştirme sunucusunda /api isteklerini yerel core-api'ye yönlendir
// (container içinde nginx aynı işi yapar: /api/ -> http://core-api:8000/).
//
// `vite build --mode mock` (npm run build:mock): portal tamamen örnek veriyle çalışır
// (VITE_MOCK=1); arka uç gerekmez. Ekranda "ÖRNEK VERİ" rozeti görünür.
export default defineConfig(({ mode }) => ({
  plugins: [react(), fontOnyukleme()],
  define: mode === "mock" ? { "import.meta.env.VITE_MOCK": JSON.stringify("1") } : {},
  build: {
    // Font dosyaları asla data: URI olarak gömülmez: nginx CSP'si (default-src 'self', font-src yok)
    // data: fontu engeller. JetBrains Mono'nun 2 KB'lık alt kümesi aksi halde 4 KB sınırının altında kalır.
    assetsInlineLimit: (dosya: string) => (/\.woff2?$/.test(dosya) ? false : undefined),
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
}));
