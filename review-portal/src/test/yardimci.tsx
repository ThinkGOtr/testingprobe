import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api/client";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { goruntulemeyiKaydetTest } from "../components/CaseKarti";
import { mockVerisi } from "../api/mock/handlers";
import type { TestCase } from "../api/types";

/** Mock oturumu açar (kullanıcı adı rolü belirler: analist, muhendis, sunucu, po, testci). */
export async function oturumAc(kullanici = "analist") {
  return api.login(kullanici, "Demo123!");
}

/**
 * K13' (tur 3): toplu onay uygunluğu yalnız yerel 3 sn kümesine dayanır. Testte case'leri oturumdaki
 * kullanıcı için bu oturumda 3 sn görülmüş sayar (oturum açıkken çağrılır).
 */
export async function yereldeGorulmus(caseler: (string | Pick<TestCase, "id" | "durum" | "karar" | "karar_zamani">)[]) {
  const k = await api.me();
  for (const c of caseler) {
    // Kimlik verilirse örnek verideki case'in güncel durumu (012: taslak ya da onaya hazır) kullanılır;
    // örnek veride yoksa karar verilmemiş taslak sayılır.
    const m = typeof c === "string" ? mockVerisi().caseler.find((x) => x.id === c) : undefined;
    const kayit = typeof c !== "string" ? c : m ? m : { id: c, durum: "draft" as const, karar: null, karar_zamani: null };
    goruntulemeyiKaydetTest(k.id || k.kullanici_adi, kayit);
  }
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
