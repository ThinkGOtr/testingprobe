// "Gherkin indir" (specs/011 F8, K14): onaylı ve hazır güncel case'lerin Türkçe Gherkin'i.
// Dönüşüm çekirdektedir (`GET /requirements/{id}/cases.feature`, deterministik, model çağrısı yok);
// portal yalnız kaç case'in dahil olacağını gösterir ve dosyayı indirir.
import { useState } from "react";
import { api } from "../api/client";
import { hataMesaji } from "../api/http";
import type { TestCase } from "../api/types";
import { caseHazirlik } from "../lib/caseV3";
import { IslemDugmesi } from "./ui";

/** Çekirdekle aynı kural: onaylı/yayınlanmış + hazır + güncel (önceki içeriğe ait değil). */
export function gherkinUygun(c: TestCase): boolean {
  return (c.durum === "approved" || c.durum === "published") && caseHazirlik(c) === "ready" && !c.onceki_icerik;
}

export const GHERKIN_YOK_NEDENI = "Gherkin'e aktarılacak case yok: yalnız onaylı (ya da yayınlanmış) ve hazır case'ler dahil edilir.";

export function gherkinDosyaAdi(anahtar: string): string {
  return `${anahtar.replace(/[^A-Za-z0-9._-]/g, "_") || "gereksinim"}.feature`;
}

function indir(metin: string, dosyaAdi: string): void {
  const url = URL.createObjectURL(new Blob([metin], { type: "text/plain;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = dosyaAdi;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function GherkinIndir({ requirementId, anahtar, caseler }: { requirementId: string; anahtar: string; caseler: TestCase[] }) {
  const [calisiyor, setCalisiyor] = useState(false);
  const [hata, setHata] = useState<string | null>(null);
  const uygun = caseler.filter(gherkinUygun).length;
  const disarida = caseler.filter((c) => c.durum !== "superseded" && c.durum !== "rejected").length - uygun;

  async function tikla() {
    setCalisiyor(true);
    setHata(null);
    try {
      indir(await api.gherkin(requirementId), gherkinDosyaAdi(anahtar));
    } catch (e) {
      setHata(hataMesaji(e));
    } finally {
      setCalisiyor(false);
    }
  }

  return (
    <span className="gherkin-indir" data-testid="gherkin-indir">
      <IslemDugmesi tur="ikincil" disabled={uygun === 0} title={uygun === 0 ? GHERKIN_YOK_NEDENI : undefined} calisiyor={calisiyor} onClick={() => void tikla()}>
        Gherkin indir
      </IslemDugmesi>
      {uygun > 0 && (
        <span className="soluk kucuk" data-testid="gherkin-sayisi">
          {" "}
          {uygun} case dahil{disarida > 0 ? ` · ${disarida} case onay/hazırlık bekliyor (dahil değil)` : ""}
        </span>
      )}
      {hata && (
        <span className="hata-metni kucuk" role="alert">
          {" "}
          {hata}
        </span>
      )}
    </span>
  );
}
