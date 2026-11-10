// `<aiprobe-switcher>` yükleyicisi (PLAN §2.3 değiştirici; specs/010-aiprobe-sso T042).
//
// Değiştirici `aiprobe-platform/packages/switcher/src/switcher.js`'den **vendor**'lanır:
// `src/vendor/aiprobe-switcher/switcher-<sürüm>.js` bayt bayt aynı kopyadır (sha384 testte
// sabitlenir: `degistirici.test.ts`; sürüm yükseltme = bu repoda PR). Paketle birlikte aynı kökenden
// sunulur, CDN yok: nginx CSP'si `script-src 'self'` (default-src) korunur. Yalnız AI Probe kipinde
// (`aiprobe`/`both`) dinamik `import()` ile yüklenir; `local` kipte parça hiç istenmez.

import type { AiprobeSwitcher } from "../vendor/aiprobe-switcher/switcher-1.0.2.js";

export const DEGISTIRICI_SURUMU = "1.0.2";

let soz: Promise<void> | null = null;

export function degistiriciyiYukle(): Promise<void> {
  soz ??= import("../vendor/aiprobe-switcher/switcher-1.0.2.js")
    .then(() => customElements.whenDefined("aiprobe-switcher"))
    .then(() => undefined)
    .catch((e: unknown) => {
      soz = null;
      throw e;
    });
  return soz;
}

export type { AiprobeSwitcher };
