import { useState } from "react";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import type { McpToken, TokenKapsami } from "../api/types";
import { useBildirim } from "../components/Bildirim";
import { BosDurum, Cip, HataKutusu, IslemDugmesi, Kart, SayfaBasligi, Uyari, Yukleniyor } from "../components/ui";
import { useIslem, useVeri } from "../hooks";
import { tarih } from "../lib/format";

/** `.mcp.json` sunucu adı (Claude Code araçları `mcp__testing-probe__*` olarak görür). */
export const MCP_SUNUCU_ADI = "testing-probe";
/** Token'ı repoya yazmamak için ortam değişkeni (Claude Code `.mcp.json`'da `${VAR}` açar). */
export const MCP_TOKEN_DEGISKENI = "TP_MCP_TOKEN";

/**
 * Claude Code `.mcp.json` parçası (HTTP taşıma, bearer başlığı). `gomulu=false` (önerilen):
 * başlık `${TP_MCP_TOKEN}` ortam değişkeninden okunur; dosya git'e girse bile token girmez.
 */
export function mcpJson(t: Pick<McpToken, "mcp_url" | "token">, gomulu = true): string {
  return JSON.stringify(
    {
      mcpServers: {
        [MCP_SUNUCU_ADI]: {
          type: "http",
          url: t.mcp_url,
          headers: { Authorization: `Bearer ${gomulu ? t.token : `\${${MCP_TOKEN_DEGISKENI}}`}` },
        },
      },
    },
    null,
    2,
  );
}

/** Aynı kaydı `.mcp.json`'u elle düzenlemeden ekleyen Claude Code komutu (proje kapsamı). */
export function claudeMcpKomutu(t: Pick<McpToken, "mcp_url">): string {
  return `claude mcp add --transport http --scope project ${MCP_SUNUCU_ADI} ${t.mcp_url} --header "Authorization: Bearer \${${MCP_TOKEN_DEGISKENI}}"`;
}

const KAPSAM: Record<TokenKapsami, { ad: string; aciklama: string }> = {
  submit: { ad: "submit", aciklama: "submit_draft_cases: Claude Code'un ürettiği taslak case'ler portala 'karar bekliyor' olarak düşer. Jira'ya yazmaz." },
  publish: { ad: "publish", aciklama: "publish_test_cases: yalnızca portalda onaylanmış case kimliklerini yayınlar." },
};

export function ClaudeCode() {
  const [kapsam, setKapsam] = useState<TokenKapsami>("submit");
  const [token, setToken] = useState<McpToken | null>(null);
  const [kanalKapali, setKanalKapali] = useState<string | null>(null);
  const tokenlar = useVeri(() => api.tokenlar(), []);
  const islem = useIslem();
  const iptal = useIslem();
  const bildir = useBildirim();

  async function kopyala(metin: string) {
    try {
      await navigator.clipboard.writeText(metin);
      bildir("Panoya kopyalandı.");
    } catch {
      bildir("Kopyalanamadı; metni elle seçin.", "hata");
    }
  }

  async function olustur() {
    setKanalKapali(null);
    try {
      const t = await api.tokenOlustur(kapsam);
      setToken(t);
      void tokenlar.yenile(true);
    } catch (e) {
      // 501: core'da /mcp ucu henüz bağlı değil — token üretilmez (çalışmayan kimlik dağıtılmaz).
      if (e instanceof ApiError && e.status === 501) setKanalKapali(e.detail);
      else await islem.calistir(() => Promise.reject(e));
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
        <IslemDugmesi roller={["analyst"]} calisiyor={islem.calisiyor} onClick={olustur}>
          8 saatlik token oluştur
        </IslemDugmesi>
        {kanalKapali && (
          <Uyari ton="bilgi" baslik="IDE (MCP) kanalı henüz etkin değil">
            {kanalKapali}. Çekirdekte <span className="mono">/mcp</span> ucu bağlanınca token üretilebilir; o zamana kadar çalışmayan bir
            kimlik bilgisi ve <span className="mono">.mcp.json</span> verilmez.
          </Uyari>
        )}
        {islem.hata && <HataKutusu hata={islem.hata} kaynak={islem.hataNesnesi} />}
      </Kart>

      {token && (
        <Kart baslik="Claude Code'a bağlama">
          <Uyari>
            Token yalnızca şimdi gösterilir. Son kullanma: {tarih(token.son_kullanma)}. Parolanız değişirse geçersizleşir. Git'e eklemeyin.
          </Uyari>
          <ol className="adim-liste">
            <li>
              <p className="kucuk">Token'ı kabuğunuzda ortam değişkenine yazın (dosyaya değil):</p>
              <pre className="kod-blok" tabIndex={0} aria-label="Ortam değişkeni komutu">
                <code>{`export ${MCP_TOKEN_DEGISKENI}=${token.token}`}</code>
              </pre>
              <div className="eylemler">
                <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={() => kopyala(`export ${MCP_TOKEN_DEGISKENI}=${token.token}`)}>
                  Komutu kopyala
                </button>
              </div>
            </li>
            <li>
              <p className="kucuk">
                Proje kökündeki <span className="mono">.mcp.json</span> dosyasına ekleyin (token değişkenden okunur; dosya repoya girebilir):
              </p>
              <pre className="kod-blok" tabIndex={0} aria-label=".mcp.json (ortam değişkeniyle)">
                <code>{mcpJson(token, false)}</code>
              </pre>
              <p className="kucuk soluk">Ya da dosyayı elle düzenlemeden, tek komutla:</p>
              <pre className="kod-blok" tabIndex={0} aria-label="claude mcp add komutu">
                <code>{claudeMcpKomutu(token)}</code>
              </pre>
              <div className="eylemler">
                <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={() => kopyala(mcpJson(token, false))}>
                  .mcp.json'u kopyala
                </button>
                <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => kopyala(claudeMcpKomutu(token))}>
                  claude mcp add komutunu kopyala
                </button>
              </div>
            </li>
            <li>
              <p className="kucuk">
                Claude Code'da <span className="mono">/mcp</span> ile <span className="mono">{MCP_SUNUCU_ADI}</span> sunucusunun bağlandığını
                görün; <span className="mono">submit_draft_cases(requirement_key, cases[])</span> ile taslak gönderin. Case'ler "Case review"
                ekranında <strong>Claude Code</strong> etiketiyle görünür ve yine portalda onaylanır.
              </p>
            </li>
          </ol>
          <details>
            <summary className="kucuk">Token gömülü .mcp.json (yalnızca kişisel, repoya girmeyen dosya için)</summary>
            <pre className="kod-blok" tabIndex={0} aria-label=".mcp.json içeriği">
              <code>{mcpJson(token)}</code>
            </pre>
            <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => kopyala(token.token)}>
              Yalnızca token'ı kopyala
            </button>
          </details>
        </Kart>
      )}

      <Kart baslik="Token'larım">
        {tokenlar.yukleniyor && !tokenlar.veri ? (
          <Yukleniyor />
        ) : tokenlar.hata && !tokenlar.veri ? (
          <HataKutusu hata={tokenlar.hata} kaynak={tokenlar.hataNesnesi} yenile={() => void tokenlar.yenile()} />
        ) : !tokenlar.veri?.length ? (
          <BosDurum baslik="Henüz token yok." />
        ) : (
          <div className="tablo-sarici" tabIndex={0} role="region" aria-label="Token listesi">
            <table className="tablo tablo-sik">
              <thead>
                <tr>
                  <th scope="col">Kapsam</th>
                  <th scope="col">Oluşturma</th>
                  <th scope="col">Son kullanma</th>
                  <th scope="col">Son kullanım</th>
                  <th scope="col">Durum</th>
                  <th scope="col">
                    <span className="gorunmez">İşlem</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {tokenlar.veri.map((t) => {
                  const suresiDoldu = Date.parse(t.son_kullanma) < Date.now();
                  return (
                    <tr key={t.id}>
                      <td className="mono">{t.kapsam}</td>
                      <td>{tarih(t.olusturma)}</td>
                      <td>{tarih(t.son_kullanma)}</td>
                      <td>{t.son_kullanim ? tarih(t.son_kullanim) : "—"}</td>
                      <td>
                        {t.iptal ? <Cip ton="notr">İptal</Cip> : suresiDoldu ? <Cip ton="notr">Süresi doldu</Cip> : <Cip ton="basari">Etkin</Cip>}
                      </td>
                      <td>
                        {!t.iptal && !suresiDoldu && (
                          <IslemDugmesi
                            roller={["analyst"]}
                            kucuk
                            tur="tehlike"
                            calisiyor={iptal.calisiyor}
                            aria-label={`${t.kapsam} token'ını iptal et`}
                            onClick={async () => {
                              const s = await iptal.calistir(() => api.tokenIptal(t.id).then(() => true));
                              if (s) {
                                bildir("Token iptal edildi.");
                                void tokenlar.yenile(true);
                              }
                            }}
                          >
                            İptal et
                          </IslemDugmesi>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {iptal.hata && <HataKutusu hata={iptal.hata} kaynak={iptal.hataNesnesi} />}
      </Kart>
    </>
  );
}
