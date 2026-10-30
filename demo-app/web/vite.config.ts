import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Geliştirmede /api çağrıları yerel demo-app-api'ye gider; konteynerde nginx proxy'ler.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
