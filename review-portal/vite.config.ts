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
