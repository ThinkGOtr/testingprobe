// duman-ortami.mjs tür bildirimi (test/duman.test.ts için).
type Platform = 'android' | 'ios' | 'windows';
type Ortam = Record<string, string | undefined>;

export const PLATFORMLAR: Platform[];
export const VARSAYILAN_WINDOWS_VM_APPIUM: string;
export const DEMO_WINDOWS_APP: string;
export const DEMO_UYGULAMA: string;
export const BEKLENEN_STRATEJI: Record<Platform, 'id' | 'accessibilityId'>;
export function appiumAdresi(platform: string, ortam: Ortam): string;
export function stokOrtami(
  platform: string,
  ortam: Ortam,
  iosUdid?: string,
  harici?: boolean,
): { env: Record<string, string>; hedef: RegExp | null } | undefined;
export function demoOrtami(platform: string, ortam: Ortam, iosUdid?: string): Record<string, string> | undefined;
export function uygulamaKimligi(platform: string, env: Record<string, string>): string;
