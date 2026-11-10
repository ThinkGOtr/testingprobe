// Expo yapılandırma eklentisi: demo API'ye düz HTTP izni — YALNIZCA belirli yerel adreslere.
//
// Demo API TLS'siz (http://…:8081). Varsayılan olarak:
//   Android (API 28+) düz HTTP'yi engeller → res/xml/network_security_config.xml ile yalnızca
//   10.0.2.2 (emülatörden host), 127.0.0.1 ve localhost için cleartext açılır; geri kalan her
//   alan adı için platform varsayılanı (yalnız HTTPS) geçerlidir. `usesCleartextTraffic=true`
//   (her yere izin) bilerek KULLANILMAZ.
//   iOS ATS: NSExceptionDomains ile aynı adresler için NSExceptionAllowsInsecureHTTPLoads.
// Derleme anında EXPO_PUBLIC_API_URL(_ANDROID|_IOS) http:// ile başka bir hosta işaret ediyorsa o
// host da listeye eklenir (ör. aynı ağdaki gerçek cihaz → Mac'in LAN adresi).
const fs = require("node:fs");
const path = require("node:path");
const { withAndroidManifest, withDangerousMod, withInfoPlist } = require("expo/config-plugins");

const SABIT = ["10.0.2.2", "127.0.0.1", "localhost"];

function httpHostu(url) {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "http:" ? u.hostname : null;
  } catch {
    return null;
  }
}

function hostlar(platform) {
  const ozel = platform === "android" ? process.env.EXPO_PUBLIC_API_URL_ANDROID : process.env.EXPO_PUBLIC_API_URL_IOS;
  const ek = [httpHostu(process.env.EXPO_PUBLIC_API_URL), httpHostu(ozel)].filter(Boolean);
  return [...new Set([...SABIT, ...ek])];
}

function xmlKacis(s) {
  return s.replace(/[<>&"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function withAndroidCleartext(config) {
  config = withDangerousMod(config, [
    "android",
    async (cfg) => {
      const dizin = path.join(cfg.modRequest.platformProjectRoot, "app", "src", "main", "res", "xml");
      fs.mkdirSync(dizin, { recursive: true });
      const alanlar = hostlar("android")
        .map((h) => `        <domain includeSubdomains="false">${xmlKacis(h)}</domain>`)
        .join("\n");
      const xml = `<?xml version="1.0" encoding="utf-8"?>
<!-- Üretildi: plugins/ag-guvenligi.js — elle düzenlemeyin (expo prebuild yeniden yazar). -->
<network-security-config>
    <base-config cleartextTrafficPermitted="false" />
    <domain-config cleartextTrafficPermitted="true">
${alanlar}
    </domain-config>
</network-security-config>
`;
      fs.writeFileSync(path.join(dizin, "network_security_config.xml"), xml);
      return cfg;
    },
  ]);
  return withAndroidManifest(config, (cfg) => {
    const app = cfg.modResults.manifest.application?.[0];
    if (app) {
      app.$["android:networkSecurityConfig"] = "@xml/network_security_config";
      // Şablonun olası genel izni ağ yapılandırmasını gölgelemesin.
      delete app.$["android:usesCleartextTraffic"];
    }
    return cfg;
  });
}

function withIosAts(config) {
  return withInfoPlist(config, (cfg) => {
    const ats = cfg.modResults.NSAppTransportSecurity ?? {};
    ats.NSAllowsArbitraryLoads = false;
    ats.NSAllowsLocalNetworking = true;
    const istisnalar = ats.NSExceptionDomains ?? {};
    for (const h of hostlar("ios")) {
      istisnalar[h] = { NSExceptionAllowsInsecureHTTPLoads: true, NSIncludesSubdomains: false };
    }
    ats.NSExceptionDomains = istisnalar;
    cfg.modResults.NSAppTransportSecurity = ats;
    return cfg;
  });
}

module.exports = function withAgGuvenligi(config) {
  return withIosAts(withAndroidCleartext(config));
};
