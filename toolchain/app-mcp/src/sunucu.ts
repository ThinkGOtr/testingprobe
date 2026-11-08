/**
 * Streamable HTTP sunucusu (`/mcp`, Playwright MCP gibi). Durumlu: MCP oturumu başına bir
 * `McpServer` + bir `AppOturumu` (tek Appium oturumu). MCP oturumu kapanınca (DELETE /mcp ya da
 * bağlantı kapanışı) ve boşta kalma süresi dolunca Appium oturumu kapatılır.
 *
 * Host başlığı denetimi (DNS rebinding): yalnızca APP_MCP_ALLOWED_HOSTS. `/health` sağlık ucu.
 */
import { randomUUID } from 'node:crypto';
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { isInitializeRequest } from '@modelcontextprotocol/sdk/types.js';
import { sunucuKur } from './araclar.js';
import { AppOturumu, CihazKilidi } from './oturum.js';
import type { SurucuFabrikasi } from './surucu.js';
import type { Ayarlar } from './yapilandirma.js';

const MAKS_GOVDE = 1024 * 1024;
const MAKS_OTURUM = 8;

interface Kayit {
  tasima: StreamableHTTPServerTransport;
  oturum: AppOturumu;
}

export interface AppMcpSunucusu {
  http: Server;
  oturumlar: Map<string, Kayit>;
  /** Boşta süresi dolan oturumları kapatır (zamanlayıcı da bunu çağırır). */
  bostaDenetle(): Promise<void>;
  kapat(): Promise<void>;
}

function json(res: ServerResponse, kod: number, govde: unknown): void {
  res.writeHead(kod, { 'content-type': 'application/json' }).end(JSON.stringify(govde));
}

function rpcHata(res: ServerResponse, kod: number, mesaj: string): void {
  json(res, kod, { jsonrpc: '2.0', error: { code: -32000, message: mesaj }, id: null });
}

async function govdeOku(req: IncomingMessage): Promise<unknown> {
  const parcalar: Buffer[] = [];
  let boy = 0;
  for await (const p of req) {
    boy += (p as Buffer).length;
    if (boy > MAKS_GOVDE) throw new Error('istek gövdesi çok büyük');
    parcalar.push(p as Buffer);
  }
  const metin = Buffer.concat(parcalar).toString('utf8');
  return metin ? JSON.parse(metin) : undefined;
}

export function sunucuOlustur(ayar: Ayarlar, fabrika: SurucuFabrikasi, log: (m: string) => void = () => {}): AppMcpSunucusu {
  const kilit = new CihazKilidi();
  const oturumlar = new Map<string, Kayit>();

  const oturumuKapat = async (kimlik: string, neden: string): Promise<void> => {
    const k = oturumlar.get(kimlik);
    if (!k) return;
    oturumlar.delete(kimlik);
    log(`oturum kapandı ${kimlik.slice(0, 8)} (${neden})`);
    await k.oturum.kapat();
    await k.tasima.close().catch(() => undefined);
  };

  const bostaDenetle = async (): Promise<void> => {
    const sinir = Date.now() - ayar.bostaSn * 1000;
    const kapanacak = [...oturumlar].filter(([, k]) => !k.oturum.mesgul && k.oturum.sonEtkinlik < sinir);
    await Promise.all(kapanacak.map(([kimlik]) => oturumuKapat(kimlik, 'boşta zaman aşımı')));
  };
  const bostaDenetim = setInterval(() => void bostaDenetle(), Math.min(30_000, ayar.bostaSn * 250));
  bostaDenetim.unref();

  const http = createServer((req, res) => {
    void (async () => {
      const url = new URL(req.url ?? '/', 'http://x');
      const host = (req.headers.host ?? '').toLowerCase();
      if (!ayar.izinliHostlar.includes(host)) {
        rpcHata(res, 403, 'Host izinli değil');
        return;
      }
      if (url.pathname === '/health' && req.method === 'GET') {
        json(res, 200, { durum: 'ok', oturum: oturumlar.size, platformlar: Object.keys(ayar.platformlar) });
        return;
      }
      if (url.pathname !== '/mcp') {
        json(res, 404, { hata: 'bulunamadı' });
        return;
      }
      const sid = req.headers['mcp-session-id'];
      const kimlik = typeof sid === 'string' ? sid : undefined;
      if (req.method === 'POST') {
        let govde: unknown;
        try {
          govde = await govdeOku(req);
        } catch (e) {
          rpcHata(res, 400, (e as Error).message);
          return;
        }
        if (kimlik) {
          const k = oturumlar.get(kimlik);
          if (!k) {
            rpcHata(res, 404, 'MCP oturumu bulunamadı');
            return;
          }
          await k.tasima.handleRequest(req, res, govde);
          return;
        }
        if (!isInitializeRequest(govde)) {
          rpcHata(res, 400, 'Oturum kimliği yok: önce initialize');
          return;
        }
        if (oturumlar.size >= MAKS_OTURUM) {
          rpcHata(res, 503, 'Çok fazla açık MCP oturumu');
          return;
        }
        let oturum: AppOturumu | undefined;
        const tasima: StreamableHTTPServerTransport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => randomUUID(),
          onsessioninitialized: (yeni) => {
            oturum = new AppOturumu(yeni, ayar, fabrika, kilit);
            oturumlar.set(yeni, { tasima, oturum });
            log(`oturum açıldı ${yeni.slice(0, 8)}`);
          },
        });
        tasima.onclose = () => {
          if (tasima.sessionId) void oturumuKapat(tasima.sessionId, 'bağlantı kapandı');
        };
        // Oturum nesnesi initialize'da oluşur; sunucu ona tembel vekil üzerinden bağlanır.
        const vekil = new Proxy({} as AppOturumu, {
          get(_h, ad) {
            if (!oturum) throw new Error('oturum hazır değil');
            const v = Reflect.get(oturum, ad, oturum) as unknown;
            return typeof v === 'function' ? (v as (...a: unknown[]) => unknown).bind(oturum) : v;
          },
        });
        await sunucuKur(vekil).connect(tasima);
        await tasima.handleRequest(req, res, govde);
        return;
      }
      if (req.method === 'GET' || req.method === 'DELETE') {
        const k = kimlik ? oturumlar.get(kimlik) : undefined;
        if (!k) {
          rpcHata(res, 404, 'MCP oturumu bulunamadı');
          return;
        }
        await k.tasima.handleRequest(req, res);
        if (req.method === 'DELETE') await oturumuKapat(kimlik!, 'istemci kapattı');
        return;
      }
      res.writeHead(405, { allow: 'GET, POST, DELETE' }).end();
    })().catch((e: unknown) => {
      log(`istek hatası: ${(e as Error).message}`);
      if (!res.headersSent) rpcHata(res, 500, 'iç hata');
    });
  });

  return {
    http,
    oturumlar,
    bostaDenetle,
    async kapat() {
      clearInterval(bostaDenetim);
      await Promise.all([...oturumlar.keys()].map((k) => oturumuKapat(k, 'sunucu kapanıyor')));
      await new Promise<void>((r) => http.close(() => r()));
    },
  };
}
