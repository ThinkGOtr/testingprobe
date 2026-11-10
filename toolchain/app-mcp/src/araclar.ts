/**
 * app-mcp araç yüzeyi (specs/009-mobil-masaustu §2.6). Bu liste KAPALIDIR: kod çalıştırma,
 * `mobile:` / `execute` komutları, uygulama kurma/kaldırma, dosya aktarımı, serbest XPath sorgusu
 * ve snapshot dışında kaynak dökümü aracı YOKTUR. `app_screenshot` yalnızca çekirdeğin canlı
 * görünüm kanalı içindir (ajanın izin listesinde yok, çekirdekte FORBIDDEN_TOOLS'ta).
 *
 * Argüman adları Playwright MCP eşleriyle aynı (`ref`, `element`, `text`, `values`, `textGone`,
 * `time`); bilinmeyen argüman reddedilir (strict şema). `filename` gibi dosyaya yazan argüman yok.
 */
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js';
import { z } from 'zod';
import { PLATFORMLAR } from './agac.js';
import { AracHatasi, type AppOturumu, type AracCiktisi } from './oturum.js';

export const ARACLAR = [
  'app_launch',
  'app_snapshot',
  'app_click',
  'app_type',
  'app_select_option',
  'app_wait_for',
  'app_generate_locator',
  'app_screenshot',
] as const;

const REF = z
  .string()
  .regex(/^e\d{1,6}$/, 'ref son snapshottaki eN biçiminde olmalı')
  .describe('Son app_snapshot çıktısındaki elemanın ref değeri (ör. e12)');
const ELEMAN = z
  .string()
  .max(200)
  .optional()
  .describe('Elemanın insan okunur tarifi (kayıt ve izinde gösterilir)');

function sonuc(c: AracCiktisi): CallToolResult {
  const content: CallToolResult['content'] = [{ type: 'text', text: c.metin }];
  if (c.resim) content.push({ type: 'image', data: c.resim, mimeType: 'image/png' });
  return { content };
}

function hata(e: unknown): CallToolResult {
  const mesaj = e instanceof AracHatasi ? e.message : `beklenmeyen hata: ${e instanceof Error ? e.message.split('\n')[0] : String(e)}`;
  return { content: [{ type: 'text', text: `### Hata\n${mesaj}` }], isError: true };
}

/** Oturuma bağlı MCP sunucusu (MCP oturumu başına bir tane). */
export function sunucuKur(oturum: AppOturumu): McpServer {
  const sunucu = new McpServer(
    { name: 'tp-app-mcp', version: '0.1.0' },
    {
      instructions:
        'Mobil/masaüstü uygulamayı Appium üstünden sürer. Önce app_launch, sonra app_snapshot; ' +
        'eylemler son snapshot\'taki ref ile yapılır ve her eylem güncel snapshot döndürür.',
    },
  );
  const yurut = (is: () => Promise<AracCiktisi>) =>
    oturum.calistir(is).then(sonuc, hata);

  sunucu.registerTool(
    'app_launch',
    {
      title: 'Uygulamayı başlat',
      description:
        'Yapılandırılmış uygulamayı verilen platformda sıfırdan başlatır (çalışıyorsa kapatıp açar) ve ' +
        'ekranın snapshot\'ını döndürür. Uygulama kimliği yapılandırmadan gelir. reset=true uygulama ' +
        'verisini temizleyerek yeni oturum açar.',
      inputSchema: z
        .object({
          platform: z.enum(PLATFORMLAR as [string, ...string[]]).describe('android | ios | windows'),
          reset: z.boolean().optional().describe('Uygulama verisini sıfırla (varsayılan false)'),
        })
        .strict(),
      annotations: { destructiveHint: false, openWorldHint: false },
    },
    (a) => yurut(() => oturum.baslat(a.platform as (typeof PLATFORMLAR)[number], a.reset ?? false)),
  );

  sunucu.registerTool(
    'app_snapshot',
    {
      title: 'Ekran snapshot\'ı',
      description:
        'Ekranın erişilebilirlik ağacını döndürür: satır başına bir eleman — rol, görünen ad, ' +
        '[id=…] erişilebilirlik kimliği, durum ve [ref=eN]. Eylemler bu ref\'lerle yapılır.',
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    () => yurut(() => oturum.snapshot()),
  );

  sunucu.registerTool(
    'app_click',
    {
      title: 'Tıkla',
      description: 'Elemana dokunur/tıklar.',
      inputSchema: z.object({ element: ELEMAN, ref: REF }).strict(),
      annotations: { destructiveHint: false, openWorldHint: false },
    },
    (a) => yurut(() => oturum.tikla(a.ref, a.element)),
  );

  sunucu.registerTool(
    'app_type',
    {
      title: 'Yaz',
      description:
        'Metin alanını temizleyip metni yazar. Parola alanına yazılan metin hiçbir çıktıda gösterilmez.',
      inputSchema: z
        .object({ element: ELEMAN, ref: REF, text: z.string().max(2000).describe('Yazılacak metin') })
        .strict(),
      annotations: { destructiveHint: false, openWorldHint: false },
    },
    (a) => yurut(() => oturum.yaz(a.ref, a.text, a.element)),
  );

  sunucu.registerTool(
    'app_select_option',
    {
      title: 'Seçenek seç',
      description: 'Seçicide (açılır liste / çark) görünen adıyla tek bir seçenek seçer.',
      inputSchema: z
        .object({
          element: ELEMAN,
          ref: REF,
          values: z.array(z.string().max(200)).min(1).max(1).describe('Seçilecek seçeneğin görünen adı (tek değer)'),
        })
        .strict(),
      annotations: { destructiveHint: false, openWorldHint: false },
    },
    (a) => yurut(() => oturum.secenekSec(a.ref, a.values, a.element)),
  );

  sunucu.registerTool(
    'app_wait_for',
    {
      title: 'Bekle',
      description:
        'Metnin görünmesini (text), kaybolmasını (textGone) ya da süreyi (time, saniye) bekler. ' +
        'Üst sınır yapılandırmadadır (varsayılan 10 sn).',
      inputSchema: z
        .object({
          text: z.string().max(200).optional().describe('Görünmesi beklenen metin'),
          textGone: z.string().max(200).optional().describe('Kaybolması beklenen metin'),
          time: z.number().positive().optional().describe('Beklenecek süre (saniye)'),
        })
        .strict(),
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    (a) => yurut(() => oturum.bekle(a)),
  );

  sunucu.registerTool(
    'app_generate_locator',
    {
      title: 'Locator üret',
      description:
        'Elemanın kalıcı locator\'ını döndürür: {platform, strategy, id}. Elemanın erişilebilirlik ' +
        'kimliği yoksa id null olur (locator eksik).',
      inputSchema: z.object({ element: ELEMAN, ref: REF }).strict(),
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    (a) => yurut(() => oturum.locator(a.ref)),
  );

  sunucu.registerTool(
    'app_screenshot',
    {
      title: 'Ekran görüntüsü (yalnız çekirdek)',
      description: 'Canlı görünüm için PNG ekran görüntüsü. Ajan araç listesinde yer almaz.',
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    () => yurut(() => oturum.ekranGoruntusu()),
  );

  return sunucu;
}
