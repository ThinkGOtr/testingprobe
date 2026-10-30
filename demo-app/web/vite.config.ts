import { defineConfig, type ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";

// /api çağrıları demo-app-api'ye gider (önek kaldırılır). Konteynerde nginx proxy'ler;
// `vite` (dev) ve `vite preview` (CI / test-runner webServer) için aynı proxy burada.
// Hedef: DEMOAPP_API_URL (varsayılan http://127.0.0.1:8000).
const apiTarget = process.env.DEMOAPP_API_URL ?? "http://127.0.0.1:8000";

const proxy: Record<string, ProxyOptions> = {
  "/api": {
    target: apiTarget,
    changeOrigin: false,
    rewrite: (path) => path.replace(/^\/api/, ""),
  },
};

export default defineConfig({
  plugins: [react()],
  server: { proxy },
  preview: { proxy },
});
