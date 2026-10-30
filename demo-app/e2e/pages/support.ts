// Page object yardımcıları. locators.ts dosyaları saf veridir. Ürüne/siparişe göre değişen
// testId'ler locators.ts'te önek olarak tutulur (sonu `-`): "product-card-" + "P-001".

export interface LocatorSpec {
  readonly testId: string;
  readonly role: string;
  readonly name: string;
  readonly intent: string;
  /** Kapsayıcının testId öneki (sonu `-`); rol + ad sayfada tekrarlanıyorsa eşleşme bu kapsayıcıda aranır. */
  readonly within?: string;
}

/** Locator'ın testId değeri; önek locator'larda (sonu `-`) sonek eklenir. */
export function testIdOf(spec: LocatorSpec, suffix?: string): string {
  const isPrefix = spec.testId.endsWith("-");
  if (isPrefix && !suffix) throw new Error(`'${spec.testId}' önek locator'ı için sonek (ürün kodu / sipariş no) gerekli`);
  if (!isPrefix && suffix) throw new Error(`'${spec.testId}' sabit locator'dır; sonek verilmemeli`);
  return isPrefix ? `${spec.testId}${suffix ?? ""}` : spec.testId;
}

/** Kapsamlı locator'ın kapsayıcı testId'si: `within` + sonek (ör. "product-card-" + "P-001"). */
export function scopeTestIdOf(spec: LocatorSpec, suffix: string): string {
  if (!spec.within) throw new Error(`'${spec.testId}' kapsamlı bir locator değil (within yok)`);
  if (!spec.within.endsWith("-")) throw new Error(`'${spec.within}' kapsam öneki '-' ile bitmeli`);
  if (!suffix) throw new Error(`'${spec.testId}' kapsamı için sonek (ürün kodu) gerekli`);
  return `${spec.within}${suffix}`;
}

export const paths = {
  login: "/giris",
  catalog: "/katalog",
  cart: "/sepet",
  orders: "/siparisler",
} as const;
