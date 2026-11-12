// "Gherkin indir" (specs/011 F8, K14): onaylı ve hazır güncel case'lerin Türkçe Gherkin'i.
// Dönüşüm çekirdektedir (`GET /requirements/{id}/cases.feature`, deterministik, model çağrısı yok);
// portal yalnız kaç case'in dahil olacağını gösterir ve dosyayı indirir.
import { useId, useState } from "react";
import { api } from "../api/client";
import { hataMesaji } from "../api/http";
import type { TestCase } from "../api/types";
import { caseHazirlik } from "../lib/caseV3";
import { useBildirim } from "./Bildirim";
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

/**
 * "Gherkin indir" düğmesi. Sayfadan bağımsızdır: case review ve gereksinim sayfasında aynı imzayla
 * kullanılır. `caseler` verilmezse sayı gösterilmez ve düğme açıktır (uygun case yoksa core 404 döner).
 */
export function GherkinIndir({ requirementId, anahtar, caseler }: { requirementId: string; anahtar: string; caseler?: TestCase[] }) {
  const [calisiyor, setCalisiyor] = useState(false);
  const [hata, setHata] = useState<string | null>(null);
  const bildir = useBildirim();
  const sayiId = useId();
  const uygun = caseler ? caseler.filter(gherkinUygun).length : null;
  // Payda: güncel case'ler (reddedilen ve yerini yenisi alan case aktarılmaz, sayılmaz).
  const guncel = caseler ? caseler.filter((c) => c.durum !== "superseded" && c.durum !== "rejected").length : null;

  async function tikla() {
    setCalisiyor(true);
    setHata(null);
    try {
      const dosya = gherkinDosyaAdi(anahtar);
      indir(await api.gherkin(requirementId), dosya);
      bildir(`Gherkin dosyası indirildi: ${dosya}${uygun !== null ? ` · ${uygun} case` : ""}`);
    } catch (e) {
      setHata(hataMesaji(e));
    } finally {
      setCalisiyor(false);
    }
  }

  const sayiVar = uygun !== null && guncel !== null && uygun > 0;
  return (
    <span className="gherkin-indir" data-testid="gherkin-indir">
      <IslemDugmesi
        tur="ikincil"
        disabled={uygun === 0}
        title={uygun === 0 ? GHERKIN_YOK_NEDENI : undefined}
        calisiyor={calisiyor}
        aria-describedby={sayiVar ? sayiId : undefined}
        onClick={() => void tikla()}
      >
        Gherkin indir
      </IslemDugmesi>
      {sayiVar && (
        <span id={sayiId} className="soluk kucuk" data-testid="gherkin-sayisi" title="Yalnız onaylı (ya da yayınlanmış) ve hazır case'ler aktarılır.">
          {" "}
          {uygun}/{guncel} case dahil
          <span className="gorunmez"> (yalnız onaylı ve hazır case'ler aktarılır)</span>
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
