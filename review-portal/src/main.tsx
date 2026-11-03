import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
// Self-host fontlar (CSP default-src 'self'; Google Fonts yok). styles.css'ten önce yüklenir.
import "@fontsource-variable/inter/wght.css";
import "@fontsource-variable/jetbrains-mono/wght.css";
import "./styles.css";
import { temaOku, temaUygula } from "./lib/tema";

// İlk render'dan önce: kayıtlı tema (yoksa koyu) uygulanır; /giris dahil her ekran doğru temada açılır.
temaUygula(temaOku());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
