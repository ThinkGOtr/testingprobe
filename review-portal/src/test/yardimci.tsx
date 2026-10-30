import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api/client";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";

/** Mock oturumu açar (kullanıcı adı rolü belirler: analist, muhendis, sunucu, po, testci). */
export async function oturumAc(kullanici = "analist") {
  return api.login(kullanici, "Demo123!");
}

export function sar(ui: ReactElement, { yol = "/" }: { yol?: string } = {}) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>{ui}</BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}
