# Üretilen testler

Bu dizindeki `*.spec.ts` dosyalarını AI Testing Probe, onaylı test case'lerinden ve doğrulanmış
page object eşlemesinden **şablonla** üretir (model TypeScript yazmaz). Elle düzenlenmez; değişiklik
case'in yeniden onayı ve yeniden üretimle yapılır.

Kurallar ve izinli içe aktarmalar: `demo-app/README.md` → "Üretilen testler için sözleşme".
ESLint bu dizine ayrıca sözleşme kurallarını uygular (`npm run lint:generated-selftest`).
