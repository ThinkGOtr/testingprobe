import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, minifySync, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const TEMA_ON = fileURLToPath(new URL("./src/tema-on.js", import.meta.url));
const NGINX_CONF = fileURLToPath(new URL("./nginx.conf", import.meta.url));

/**
 * İlk boyamada tema (src/tema-on.js): kayıtlı açık/sistem tercihi paket çalışmadan uygulanır, koyu yanıp
 * sönmez. Derlemede dosya `assets/tema-on-[hash].js` olarak çıkar ve `<head>`in sonuna (stil bağlantısından
 * sonra, gövdeden önce) klasik senkron `<script src>` ile eklenir. Satır içi betik değil (nginx CSP'si:
 * `default-src 'self'`, script-src yok → inline yasak); aynı kökenli dosya izinli. public/ kullanılmaz:
 * Dockerfile yalnız src/ ve index.html'i kopyalar. Derlemede küçültülür (minifySync); geliştirme sunucusunda
 * kaynak dosya doğrudan sunulur.
 */
function temaOnBetigi(): Plugin {
  let base = "/";
  let derleme = false;
  return {
    name: "tp-tema-on",
    configResolved(c) {
      base = c.base;
      derleme = c.command === "build";
    },
    buildStart() {
      if (!derleme) return;
      // Kaynak açıklamalı; pakete küçültülmüş hâli çıkar (~1500 B → ~300 B, yorum bloğu üretime gitmez).
      const k = minifySync("tema-on.js", readFileSync(TEMA_ON, "utf8"), { compress: true, mangle: true });
      if (k.errors.length) throw new Error(`tema-on.js küçültülemedi: ${k.errors.map((h) => h.message).join("; ")}`);
      this.emitFile({ type: "asset", name: "tema-on.js", source: k.code });
    },
    transformIndexHtml: {
      order: "post",
      handler(_html, ctx) {
        const dosya = ctx.bundle ? Object.keys(ctx.bundle).find((d) => /(^|\/)tema-on-[\w-]+\.js$/.test(d)) : "src/tema-on.js";
        if (!dosya) throw new Error("tema-on.js pakette yok");
        return [{ tag: "script", attrs: { src: base + dosya }, injectTo: "head" as const }];
      },
    },
  };
}

/**
 * `vite preview` (duman e2e paketi) nginx.conf'taki CSP başlığını gönderir: CSP kapısı yalnız canlı provada
 * değil her duman koşusunda çalışır (ihlal konsola hata düşer; duman.spec.ts "CSP" testi). Yalnız preview:
 * geliştirme sunucusu HMR için satır içi betik kullanır. Başlık nginx.conf'tan okunur (tek kaynak).
 */
function onizlemeCsp(): Plugin {
  return {
    name: "tp-onizleme-csp",
    configurePreviewServer(sunucu) {
      const m = /add_header\s+Content-Security-Policy\s+"([^"]+)"/.exec(readFileSync(NGINX_CONF, "utf8"));
      if (!m) throw new Error("nginx.conf'ta Content-Security-Policy başlığı bulunamadı");
      const csp = m[1]!;
      sunucu.middlewares.use((_istek, yanit, sonraki) => {
        yanit.setHeader("Content-Security-Policy", csp);
        sonraki();
      });
    },
  };
}

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
  plugins: [react(), fontOnyukleme(), temaOnBetigi(), onizlemeCsp()],
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
