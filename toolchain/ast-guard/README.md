# ast-guard — locator onarımı için AST koruması

Constitution VI ve TEKNIK-TASARIM §8.7'nin deterministik uygulaması: locator onarımı yalnızca
`pages/**/locators.ts` içindeki `testId` değerlerini değiştirebilir. Aynı araç hem çekirdekte
(toolchain-worker `POST /ast-guard`) hem CI'da (`ast-guard` zorunlu check'i) kullanılır.

## Kullanım

```bash
npm ci --ignore-scripts && npm run build
node dist/src/cli.js --base <dizin|git-ref> --head <dizin|git-ref> \
  [--mode repair|pr] [--repo <git-repo>] [--root <e2e-kökü>] [--out rapor.json] [--quiet]
```

- `--base` / `--head`: var olan bir dizinse dizin olarak, değilse `--repo` (varsayılan: çalışma dizini)
  içindeki git ref'i olarak okunur. Karışık (dizin ↔ ref) karşılaştırma desteklenir. Dizin modunda
  `node_modules`, `.git`, `dist`, `results`, `test-results`, `playwright-report`, `allure-results` yok sayılır.
- `--root`: `pages/` dizinini içeren kök, repo/dizin köküne göre. GitHub monorepo modunda
  `demo-app/e2e`, local-forge modunda (uygulama repo kökü) `e2e`. Varsayılan `.`.
- `--mode repair` (varsayılan, en sıkı): değişen **her** dosya `<root>/pages/**/locators.ts` olmalı
  (kök dışındaki dosyalar dahil); locator dosyası eklenemez/silinemez; export ve anahtar kümeleri,
  `role`, `name`, `intent` ve `testId` dışındaki tüm alanlar aynı kalmalı; dosya metni `testId`
  literal'leri dışında bayt bayt aynı olmalı (yorum, sıra, biçim değişikliği de reddedilir).
- `--mode pr`: yalnızca değişen/eklenen `locators.ts` dosyalarının saf veri olduğunu doğrular ve
  değişen `testId`'leri, eklenen/kaldırılan girişleri raporlar. `<root>/tsconfig.json` değiştiyse
  tsc --strict kapısının gevşetilmediğini doğrular (Constitution IV): dosya silinemez, JSONC olarak
  ayrışmalı, `compilerOptions.strict: true` açıkça yazılı olmalı, strict ailesinden bayrak `false`
  yapılamaz, `extends` yasak, `files`/`include`/`exclude` tabandakiyle aynı kalmalı.
  `<root>/pages/**` ve `<root>/tsconfig.json` değişmediyse no-op.

CI'da mod `scripts/github-ast-guard-mode.sh` ile seçilir (taban daldan): `tp/repair-*` dalı, `tp-repair`
etiketi veya `tp/case-*` dışındaki her bot PR'ı → `repair`; diğerleri → `pr`. Ayrıntı: `.github/CI.md`.
Betik ve `ci.yml` sözleşmesi `test/mode-script.test.ts` ve `test/ci-workflow.test.ts` ile sınanır.

**Çıkış kodları:** `0` geçti (veya no-op) · `1` ihlal var · `2` kullanım/çalışma hatası
(ör. çözülemeyen ref; stdout'ta `{"ok": false, "error": "..."}`).

## Saf veri biçimi

```ts
// Yorumlar serbest.
export const cart = {
  addToCart: { testId: "add-to-cart", role: "button", name: "Sepete ekle", intent: "Ürün kartında sepete ekleme butonu" },
  lines: {
    subtotal: { testId: "cart-subtotal", role: "cell", name: "Ara toplam", intent: "Sepet ara toplamı" },
  },
} as const;
```

- Dosyada yalnızca `export const <ad> = { … } as const;` deyimleri bulunur (import, fonksiyon, tip,
  `let`, `export default`, ifade deyimi yasak).
- Değerler yalnızca string literal (`"…"`, `'…'`, yer tutucusuz `` `…` ``) veya iç içe nesne literal'i.
  Hesaplanan anahtar, spread, kısa yazım, metot/getter, şablon ifadesi, çağrı, tanımlayıcı başvurusu,
  sayı, birleştirme yasak.
- `testId` taşıyan nesne bir **giriş**tir: tüm alanları string'dir, alt nesne içermez. `testId`
  `^[A-Za-z0-9][A-Za-z0-9_.:-]*$` biçimindedir. Giriş kimliği `export.anahtar[.anahtar…]`.

## JSON rapor

```json
{
  "tool": "ast-guard", "schema_version": 1, "mode": "repair", "ok": true, "noop": false,
  "base": "abc…@1a2b3c4d5e6f", "head": "HEAD@…", "root": "demo-app/e2e",
  "changed_files": [{ "path": "demo-app/e2e/pages/cart/locators.ts", "status": "modified", "locator": true }],
  "testid_changes": [{ "file": "…/locators.ts", "entry": "cart.addToCart", "before": "add-to-cart", "after": "cart-add" }],
  "added_entries": [], "removed_entries": [],
  "violations": [{ "code": "field_changed", "file": "…", "line": 3, "entry": "cart.addToCart", "field": "intent", "before": "…", "after": "…", "message": "…" }],
  "summary": "AST koruması geçti (mod: repair) · değişen dosya: 1 · testId değişikliği: 1"
}
```

İhlal kodları: `non_locator_file_changed`, `locator_file_added`, `locator_file_deleted`, `base_not_pure`,
`export_added`, `export_removed`, `key_added`, `key_removed`, `field_added`, `field_removed`,
`field_changed`, `non_testid_change`, `invalid_testid`, `parse_error`, `forbidden_statement`,
`missing_as_const`, `non_literal_value`, `computed_key`, `spread`, `shorthand_property`, `method`,
`mixed_object`, `entry_missing_testid`, `duplicate_key`, `tsconfig_deleted`, `tsconfig_invalid`,
`tsconfig_extends`, `tsconfig_not_strict`, `tsconfig_strict_weakened`, `tsconfig_scope_changed`.

## Geliştirme

```bash
npm ci --ignore-scripts
npm test        # tsc (strict) + node:test
```
