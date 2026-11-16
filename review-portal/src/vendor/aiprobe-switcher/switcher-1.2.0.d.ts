// Vendor'lanmış `@aiprobe/switcher` 1.2.0 için tip bildirimi (yalnızca portalın kullandığı yüzey).
export const VERSION: string;

/** `setProjects` verisi (CONTRACT "Proje seçici (1.1.0)"; 1.2.0'da aynı, `oid` isteğe bağlı eklendi). */
export interface AiprobeProjeVerisi {
  enabled?: boolean;
  projects: { pid?: string; id?: string; name: string; org_name?: string; org?: string; oid?: string; roles: string[] }[];
  activeId?: string | null;
  roleLabels?: Record<string, string | { tr?: string; en?: string }>;
}

export class AiprobeSwitcher extends HTMLElement {
  me: unknown;
  refresh(): Promise<void>;
  open(): void;
  close(restoreFocus?: boolean): void;
  toggle(): void;
  setProjects(data: AiprobeProjeVerisi | null): void;
  openProjects(): void;
  closeProjects(restoreFocus?: boolean): void;
  /** 1.2.0: organizasyon seçici. */
  setOrgs(data: unknown): void;
  openOrgs(focus?: "checked" | "last"): void;
  closeOrgs(restoreFocus?: boolean): void;
}
