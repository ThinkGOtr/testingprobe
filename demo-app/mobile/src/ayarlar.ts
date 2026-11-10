// Demo API adresi.
//
// Varsayılan: demo-app-web nginx'i (host 127.0.0.1:8081) `/api/*` isteklerini demo-app-api'ye
// vekiller (demo-app/web/nginx.conf, docker-compose.yml). Uygulama da web gibi bu vekili kullanır;
// `/api/test/*` vekilde kapalıdır (404).
//   Android emülatörü: 10.0.2.2 = hostun geri döngü adresi.
//   iOS simülatörü: hostun ağını paylaşır, 127.0.0.1 doğrudan hosttur.
//
// Değiştirme: derleme anında `EXPO_PUBLIC_API_URL` (her iki platform) ya da platforma özel
// `EXPO_PUBLIC_API_URL_ANDROID` / `EXPO_PUBLIC_API_URL_IOS`. Expo (babel-preset-expo) bu değişkenleri
// JS paketine gömer; çalışma anında okunmaz. Sondaki `/` atılır.
import { Platform } from "react-native";

const VARSAYILAN = {
  android: "http://10.0.2.2:8081/api",
  ios: "http://127.0.0.1:8081/api",
} as const;

function sec(): string {
  // Not: Expo yalnızca `process.env.EXPO_PUBLIC_*` biçimindeki doğrudan erişimleri gömer.
  const ozel =
    Platform.OS === "android"
      ? process.env.EXPO_PUBLIC_API_URL_ANDROID
      : process.env.EXPO_PUBLIC_API_URL_IOS;
  const genel = process.env.EXPO_PUBLIC_API_URL;
  const deger = ozel || genel || (Platform.OS === "android" ? VARSAYILAN.android : VARSAYILAN.ios);
  return deger.replace(/\/+$/, "");
}

export const API_URL = sec();
