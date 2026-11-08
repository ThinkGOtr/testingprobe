// Renk ve ölçü belirteçleri — web'deki demo-app/web/src/styles.css :root değişkenlerinin aynısı.
import { StyleSheet } from "react-native";

export const renk = {
  bg: "#f4f6f8",
  surface: "#ffffff",
  text: "#17212b",
  muted: "#55606c",
  border: "#dde3e9",
  primary: "#0b5d7a",
  primarySoft: "#e3f1f6",
  accent: "#f29d38",
  accentSoft: "#fff1df",
  accentText: "#8a4b00",
  success: "#1b7a43",
  successSoft: "#e5f5ec",
  danger: "#b42318",
  dangerSoft: "#fdecea",
  warningText: "#7a4100",
  warningSoft: "#fff4e0",
  warningBorder: "#f0b860",
} as const;

export const RADIUS = 10;

export const ortak = StyleSheet.create({
  h1: { fontSize: 24, fontWeight: "700", color: renk.text },
  h2: { fontSize: 18, fontWeight: "700", color: renk.text },
  muted: { color: renk.muted, fontSize: 14 },
  metin: { color: renk.text, fontSize: 15 },
  sayfaBasi: { gap: 4, marginBottom: 16 },
  panel: {
    backgroundColor: renk.surface,
    borderColor: renk.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: RADIUS,
    padding: 16,
  },
  bos: { alignItems: "center", gap: 12, paddingVertical: 32 },
});
