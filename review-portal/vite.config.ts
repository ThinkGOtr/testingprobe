import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Geliştirme sunucusunda /api isteklerini yerel core-api'ye yönlendir
// (container içinde nginx aynı işi yapar: /api/ -> http://core-api:8000/).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
