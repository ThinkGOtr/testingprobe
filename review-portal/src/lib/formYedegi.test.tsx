import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { formlariGeriYukle, formlariSakla } from "./formYedegi";

function Form() {
  const [metin, setMetin] = useState("");
  const [onay, setOnay] = useState(false);
  return (
    <main id="ana-icerik">
      <textarea id="gerekce" value={metin} onChange={(e) => setMetin(e.target.value)} />
      <input type="checkbox" id="onay" checked={onay} onChange={(e) => setOnay(e.target.checked)} />
      <input type="password" id="gizli" defaultValue="" />
      <p data-testid="durum">
        {metin}|{String(onay)}
      </p>
    </main>
  );
}

describe("form yedeği (AI Probe yeniden girişi)", () => {
  it("doldurulmuş alanlar yedeklenir ve React durumu dahil geri konur; parola yazılmaz", async () => {
    const { unmount } = render(<Form />);
    fireEvent.change(document.getElementById("gerekce")!, { target: { value: "taslak gerekçe" } });
    fireEvent.click(document.getElementById("onay")!);
    fireEvent.change(document.getElementById("gizli")!, { target: { value: "s3cr3t" } });
    expect(formlariSakla("/gereksinimler/1", "u1")).toBe(2);
    expect(sessionStorage.getItem("tp-form-yedegi")).not.toContain("s3cr3t");
    unmount();

    render(<Form />);
    let sayi = -1;
    act(() => {
      formlariGeriYukle("/gereksinimler/1", "u1", (n) => (sayi = n));
    });
    expect(screen.getByTestId("durum")).toHaveTextContent("taslak gerekçe|true");
    expect(sayi).toBe(2);
    expect(sessionStorage.getItem("tp-form-yedegi")).toBeNull(); // tek kullanımlık
  });

  it("başka kullanıcıya ya da başka adrese geri konmaz", () => {
    const { unmount } = render(<Form />);
    fireEvent.change(document.getElementById("gerekce")!, { target: { value: "x" } });
    formlariSakla("/a", "u1");
    unmount();
    render(<Form />);
    act(() => {
      formlariGeriYukle("/b", "u1");
    });
    expect(screen.getByTestId("durum")).toHaveTextContent(/^\|false$/);
    act(() => {
      formlariGeriYukle("/a", "u2");
    });
    expect(screen.getByTestId("durum")).toHaveTextContent(/^\|false$/);
    expect(sessionStorage.getItem("tp-form-yedegi")).toBeNull(); // başka kişinin yedeği silinir
  });

  it("sahip bilinmiyorsa ya da alan boşsa yedek yazılmaz", () => {
    render(<Form />);
    expect(formlariSakla("/a", "u1")).toBe(0);
    fireEvent.change(document.getElementById("gerekce")!, { target: { value: "x" } });
    expect(formlariSakla("/a", null)).toBe(0);
    expect(sessionStorage.getItem("tp-form-yedegi")).toBeNull();
  });
});
