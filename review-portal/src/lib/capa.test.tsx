// Öneri kartı "Git" çapaları (AI-ASISTAN-PLANI §17.4): `rules/assistant/oneriler.yaml`'daki her
// `rota` + `capa` eylemi için hedef öğe ilgili sayfada DOM'da bulunur; Kabuk hash'e kaydırıp odak
// verir. rules/ Docker derleme bağlamında yok → skipIf.
import { render, screen, waitFor } from "@testing-library/react";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { MOCK_KURALLAR } from "../api/mock/oneri";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { asistanKontrolSifirla } from "../components/asistan/kontrol";
import { oturumAc } from "../test/yardimci";

const ONERILER_YAML = resolve(__dirname, "../../../rules/assistant/oneriler.yaml");

/** Ekran kalıbı → örnek veride bu bölümleri gösteren varlık. */
const ORNEK_VARLIK: Record<string, string> = {
  "/gereksinimler/:id": "req-ft-1",
  "/kod/:id": "scr-1",
  "/hatalar/:id": "fail-1",
};

/** YAML'daki `rota:` satırını izleyen `capa:` satırları (kural dosyası biçiminden bağımsız tarama). */
function yamlCapalari(metin: string): { rota: string; capa: string }[] {
  return [...metin.matchAll(/^\s*rota:\s*(\S+)\s*\n\s*capa:\s*(\S+)/gm)].map((m) => ({ rota: m[1], capa: m[2] }));
}

function uygulama(yol: string) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          <Rotalar />
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

const kaydir = vi.fn();
beforeEach(() => {
  asistanKontrolSifirla();
  kaydir.mockClear();
  Element.prototype.scrollIntoView = kaydir;
});
afterEach(() => {
  delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
});

describe("öneri çapaları", () => {
  const yaml = existsSync(ONERILER_YAML) ? yamlCapalari(readFileSync(ONERILER_YAML, "utf8")) : [];

  it.skipIf(!existsSync(ONERILER_YAML))("kural dosyasında çapalar var ve örnek veri kurallarıyla aynı", () => {
    expect(yaml.length).toBeGreaterThan(0);
    const mock = MOCK_KURALLAR.flatMap((k) => (k.eylem.tur === "rota" && k.eylem.capa ? [{ rota: k.eylem.rota, capa: k.eylem.capa }] : []));
    const sirala = (l: { rota: string; capa: string }[]) => l.map((x) => `${x.rota}#${x.capa}`).sort();
    expect(sirala(mock)).toEqual(sirala(yaml));
  });

  it.skipIf(!existsSync(ONERILER_YAML)).each(yaml)("$rota#$capa hedefi sayfada var; kaydırılır ve odaklanır", async ({ rota, capa }) => {
    const id = ORNEK_VARLIK[rota];
    expect(id, `örnek varlık tanımlı değil: ${rota}`).toBeTruthy();
    await oturumAc("analist");
    uygulama(`${rota.replace(":id", id)}#${capa}`);
    await screen.findByRole("heading", { level: 1 });
    await waitFor(() => expect(document.getElementById(capa)).not.toBeNull());
    await waitFor(() => expect(kaydir).toHaveBeenCalled());
    // Pasif düğme (ör. örnek veride "Case üret") odak alamaz; kaydırma yine yapılır.
    const el = document.getElementById(capa)!;
    if (!el.matches(":disabled")) expect(el).toHaveFocus();
  });
});
