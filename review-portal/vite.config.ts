import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Geliştirme sunucusunda /api isteklerini yerel core-api'ye yönlendir
// (container içinde nginx aynı işi yapar: /api/ -> http://core-api:8000/).
//
// `vite build --mode mock` (npm run build:mock): portal tamamen örnek veriyle çalışır
// (VITE_MOCK=1); arka uç gerekmez. Ekranda "ÖRNEK VERİ" rozeti görünür.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
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
