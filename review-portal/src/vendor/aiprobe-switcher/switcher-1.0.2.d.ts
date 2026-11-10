// Vendor'lanmış `@aiprobe/switcher` 1.0.2 için tip bildirimi (yalnızca portalın kullandığı yüzey).
export const VERSION: string;
export class AiprobeSwitcher extends HTMLElement {
  me: unknown;
  refresh(): Promise<void>;
  open(): void;
  close(restoreFocus?: boolean): void;
  toggle(): void;
}
