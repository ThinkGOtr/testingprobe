import { useState } from "react";
import { api } from "../api/client";
import type { McpToken, TokenKapsami } from "../api/types";
import { useBildirim } from "../components/Bildirim";
import { HataKutusu, IslemDugmesi, Kart, SayfaBasligi, Uyari } from "../components/ui";
import { useIslem } from "../hooks";
import { tarih } from "../lib/format";

export function mcpJson(t: McpToken): string {
  return JSON.stringify(
    {
      mcpServers: {
        "testing-probe": {
          type: "http",
          url: t.mcp_url,
          headers: { Authorization: `Bearer ${t.token}` },
        },
      },
    },
    null,
    2,
  );
}

const KAPSAM: Record<TokenKapsami, { ad: string; aciklama: string }> = {
  submit: { ad: "submit", aciklama: "submit_draft_cases: Claude Code'un ürettiği taslak case'ler portala 'karar bekliyor' olarak düşer. Jira'ya yazmaz." },
  publish: { ad: "publish", aciklama: "publish_test_cases: yalnızca portalda onaylanmış case kimliklerini yayınlar." },
};

export function ClaudeCode() {
  const [kapsam, setKapsam] = useState<TokenKapsami>("submit");
  const [token, setToken] = useState<McpToken | null>(null);
  const islem = useIslem();
  const bildir = useBildirim();

  async function kopyala(metin: string) {
    try {
      await navigator.clipboard.writeText(metin);
      bildir("Panoya kopyalandı.");
    } catch {
      bildir("Kopyalanamadı; metni elle seçin.", "hata");
    }
  }

  return (
    <>
      <SayfaBasligi
        baslik="Claude Code kanalı"
        aciklama="Ürünsüz kanal: Claude Code aynı MCP araçlarıyla taslak case gönderir; onay yine portalda insan tarafından verilir."
      />
      <Kart baslik="Token oluştur">
        <fieldset>
          <legend>Kapsam</legend>
          {(Object.keys(KAPSAM) as TokenKapsami[]).map((k) => (
            <label key={k} className="secenek-satir">
              <input type="radio" name="kapsam" value={k} checked={kapsam === k} onChange={() => setKapsam(k)} />
              <span>
                <span className="mono">{KAPSAM[k].ad}</span> — {KAPSAM[k].aciklama}
              </span>
            </label>
          ))}
        </fieldset>
        <IslemDugmesi
          roller={["analyst"]}
          calisiyor={islem.calisiyor}
          onClick={async () => {
            const t = await islem.calistir(() => api.tokenOlustur(kapsam));
            if (t) setToken(t);
          }}
        >
          8 saatlik token oluştur
        </IslemDugmesi>
        {islem.hata && <HataKutusu hata={islem.hata} />}
      </Kart>

      {token && (
        <Kart baslik=".mcp.json">
          <Uyari>Token yalnızca şimdi gösterilir. Son kullanma: {tarih(token.son_kullanma)}. Git'e eklemeyin.</Uyari>
          <p className="kucuk">Proje kökündeki <span className="mono">.mcp.json</span> dosyasına ekleyin:</p>
          <pre className="kod-blok" tabIndex={0} aria-label=".mcp.json içeriği">
            <code>{mcpJson(token)}</code>
          </pre>
          <div className="eylemler">
            <button type="button" className="dugme dugme-ikincil" onClick={() => kopyala(mcpJson(token))}>
              .mcp.json'u kopyala
            </button>
            <button type="button" className="dugme dugme-hayalet" onClick={() => kopyala(token.token)}>
              Yalnızca token'ı kopyala
            </button>
          </div>
          <p className="kucuk soluk">
            Claude Code'da: <span className="mono">submit_draft_cases(requirement_key, cases[])</span> ile taslak gönderin; case'ler "Case review"
            ekranında <strong>Claude Code</strong> etiketiyle görünür.
          </p>
        </Kart>
      )}
    </>
  );
}
