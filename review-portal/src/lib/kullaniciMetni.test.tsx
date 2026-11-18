// IA-12: iç terimler kullanıcı dilinde; ham metin "Ayrıntı"da kalır.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HataKutusu } from "../components/ui";
import { nesneEtiketi, olayEtiketi, teknikMetniCevir } from "./kullaniciMetni";

describe("kullanıcı metni (IA-12)", () => {
  it("forge deposu hatası eylem cümlesine çevrilir", () => {
    expect(teknikMetniCevir("ForgeNotFoundError: forge deposu bulunamadı: /forge/varsayilan/repo.git (scripts/forge-init.sh çalıştırın)")).toMatch(
      /^Kurulum eksik: projenin kod deposu tanımlı değil.*Depo ayarı/,
    );
    expect(teknikMetniCevir("Bilinmeyen hata")).toBeNull();
  });

  it("Sauce tetik ayarı ve manuel baz ortam değişkeni sızmaz", () => {
    expect(teknikMetniCevir("SAUCE_TETIKLER=push,nightly")).toBe("bu koşu türünde Sauce çalıştırılmıyor (proje ayarı: yalnız main'e push, gece koşularında)");
    expect(teknikMetniCevir("TP_MANUAL_BASELINE_S varsayılanı ölçüm sayılmaz")).not.toMatch(/TP_/);
  });

  it("denetim olayları ve nesneleri okunur", () => {
    expect(olayEtiketi("auth.role_switch")).toBe("Rol değiştirildi");
    expect(olayEtiketi("ai_call.recorded")).toBe("AI çağrısı kaydedildi");
    expect(olayEtiketi("codegen.pr_sync_failed")).toBe("Kod üretimi: pr sync başarısız");
    expect(nesneEtiketi("app_user:9c1c2d3e-0000-4000-8000-000000000000")).toBe("Kullanıcı 9c1c2d3e…");
    expect(nesneEtiketi("requirement:TPD-1")).toBe("Gereksinim TPD-1");
    expect(nesneEtiketi("bilinmeyen:x")).toBe("bilinmeyen:x");
  });

  it("HataKutusu bilinen hatayı kullanıcı cümlesiyle, ham metni Ayrıntı açılırında gösterir", () => {
    render(<HataKutusu hata="ForgeNotFoundError: forge deposu bulunamadı: /forge/x/repo.git (scripts/forge-init.sh çalıştırın)" kayitDisi />);
    expect(screen.getByRole("alert")).toHaveTextContent(/^Kurulum eksik/);
    expect(screen.getByText("Ayrıntı").closest("details")).toHaveTextContent(/forge-init\.sh/);
  });
});
