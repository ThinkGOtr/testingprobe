/*! @aiprobe/switcher — <aiprobe-switcher> ürün değiştirici. Bağımlılık yok, derleme gerekmez.
 *
 * Kullanım:
 *   <script type="module" src="/vendor/switcher-1.2.0.js" integrity="sha384-…"></script>
 *   <aiprobe-switcher product="testing-probe" home-origin="https://home.aiprobe.antreklabs.com" lang="tr">
 *     <div slot="product-menu"><button>Rol değiştir</button></div>
 *   </aiprobe-switcher>
 *
 * Öznitelikler: product, home-origin, me-url (vars. /auth/me), lang (tr|en),
 *               logout-url (vars. /auth/logout), account-url (vars. {home}/account),
 *               logout-method (post|get; vars. post: me.csrf_token varsa form POST, yoksa bağlantı),
 *               admin-url (verilirse ve `links` içinde admin varsa "Platform yönetimi" bağlantısı)
 *               links (1.2.0; boşlukla ayrılmış alt küme: home account admin lang logout).
 *                 Varsayılan: product="home" → "account logout" (Home kabuğu dil/yönetim/başlangıcı kendi
 *                 gösterir); diğer ürünler → "home account admin lang logout".
 *               theme (1.2.0; dark|light — yalnız zorlamak için; bkz. Tema)
 * Gizli (status=hidden) ürünler yalnız kullanıcının o üründe rolü varsa listelenir.
 *
 * Tema (1.2.0): sayfa --aip-* belirteçlerini tanımlıyorsa değiştirici onları kullanır. Tanımlanmayan belirteçlerin
 * yedek değerleri (TP görsel dili, tokens.css 2.0.0) etkin temaya göre seçilir; etkin tema sırasıyla:
 * `theme` özniteliği > sayfanın --aip-surface renginin parlaklığı > <html data-theme> > ortak çerez
 * `aiprobe_tema` (docs/tasarim/TEMA-SOZLESMESI.md; system → işletim sistemi) > koyu. Sonuç host'ta
 * `data-aip-tema="dark|light"` olarak görünür; <html> nitelik değişimi, `aiprobe:theme` olayı ve işletim sistemi
 * değişiminde yeniden hesaplanır. Değiştirici çerezi YAZMAZ (yazma ürünün tema düğmesinin işidir).
 *
 * Organizasyon seçici (1.2.0): org verilirse ızgara düğmesinin solunda "Organizasyon ▾" menü düğmesi
 * (aria-haspopup=menu; menuitemradio satırları + "Organizasyon ayarları") gösterilir. Veri:
 *   (a) data-orgs-endpoint="/api/orgs" → GET (same-origin); (b) el.setOrgs(data) / window.AIProbeSwitcher.setOrgs(data).
 *   data: {enabled?, orgs:[{id|oid, name, role?|role_label?, settings_url?}], activeId|active_id|active_oid|active:{id|oid},
 *          settingsUrl?|settings_url? ("{oid}" yer tutucusu)} ya da yalnız dizi. enabled:false / boş → gizli.
 * Seçimde cancelable `aiprobe:org-change` {oid}. preventDefault edilmezse ve data-org-switch-endpoint varsa
 * PUT {oid} → başarıda sayfa yenilenir; uç yoksa seçim yerelde uygulanır (ürün olaydan kalıcılaştırır).
 * Org verisi varken proje düğmesi org adını tekrarlamaz ve proje listesi (projelerde oid varsa) etkin org'a süzülür.
 *
 * Proje seçici (1.1.0): ürün projelerini verirse "Organizasyon · Proje" düğmesi ve açılır liste (role=listbox).
 *   (a) data-projects-endpoint="/api/projects" → GET (same-origin); (b) el.setProjects(data) / window.AIProbeSwitcher.setProjects(data).
 *   data: {enabled?, projects:[{id|pid, name, org|org_name, oid?, roles:[…]}], activeId|active_id|active:{id|pid},
 *          roleLabels?:{kod: ad}}. enabled:false ya da null → seçici gizli. Boş liste → "Atanmış proje yok".
 *   1.2.0: projeler birden çok organizasyona yayılıyorsa liste organizasyon başlıklarıyla gruplanır.
 * Seçimde cancelable `aiprobe:project-change` {pid} yayınlanır. preventDefault edilmezse ve
 * data-project-switch-endpoint verilmişse oraya PUT {pid} (JSON; me.csrf_token varsa X-CSRF-Token) gönderilir,
 * başarıda sayfa yenilenir. Uç yoksa seçimi ürün olaydan uygular (ve sayfayı kendisi yeniler).
 *
 * 1.2.0: Home kipi (product="home": panelde yalnız ürünler + Profilim + Çıkış), `links`; ürünlerde üstte
 *        "AI Probe ana sayfası" satırı; ürün durumu satırda (Açık · Kapalı/Başlat · Başlatılıyor · Erişim yok/Erişim iste);
 *        organizasyon seçici; tema (yukarıda); ortak etiket sözlüğü (LABELS: "Profilim", "Platform yönetimi"…);
 *        ≤480 px'te paneller ekran genişliğinde. Stil kancaları: ::part(org-trigger | org-name | org-panel | ctx-sep).
 * 1.1.0: proje seçici, refresh() proje ucunu da yeniden okur; açılır paneller görünür alana sığdırılır.
 *        Stil kancaları: ::part(project-trigger | project-org | project-sep | project-name | project-panel).
 * 1.0.4: products.json ?v=<VERSION>; ağ/CORS hatasında bir kez cache: 'reload'. Dil düğmesi adı = görünür metin.
 * 1.0.3: ürün bağlantısı app_url + launch_path. 1.0.2: erişim = me.products'ta kodun VARLIĞI.
 * 1.0.1: çıkış POST (CSRF) formu; gizli ürünler rol varsa görünür; admin-url; logo home-origin'e göre.
 * Özellikler:   .me (nesne verilirse me-url çağrılmaz), .refresh(), .setProjects(data), .projects, .setOrgs(data), .orgs
 * Olaylar:      aiprobe:navigate  {productId, url, kind}  — cancelable; preventDefault gezinmeyi durdurur
 *               aiprobe:lang      {lang}                  — kullanıcı dil değiştirdi (ürün kaydeder)
 *               aiprobe:project-change {pid}              — cancelable; kullanıcı proje seçti
 *               aiprobe:org-change {oid}                  — cancelable; kullanıcı organizasyon seçti
 *
 * "Başlat" (on_demand ürün kapalı): POST /api/v1/products/{id}/start Firebase ID token ister; ürün
 * sayfalarında bu token yoktur. Bu yüzden değiştirici {home}/?start=<id> adresine bağlanır; başlatmayı
 * home sayfası (kullanıcı onayıyla) yapar.
 */

export const VERSION = '1.2.0';
const DEFAULT_HOME = 'https://home.aiprobe.antreklabs.com';
const STATUS_TTL_MS = 30_000;
const LINK_KEYS = ['home', 'account', 'admin', 'lang', 'logout'];

// Ortak etiket sözlüğü (TP/AP/Home; docs/tasarim/AIPROBE-UX-DENETIM.md T1). Ürünler aynı kavram için bu adları kullanır.
const I18N = {
  tr: {
    open: 'AI Probe ürünleri', title: 'AI Probe', yours: 'Ürünleriniz', discover: 'Keşfet',
    request: 'Erişim iste', noAccess: 'Erişim yok', current: 'Buradasınız',
    stUp: 'Açık', stStopped: 'Kapalı', stStarting: 'Başlatılıyor…', start: 'Başlat',
    home: 'AI Probe ana sayfası', homeSub: 'Organizasyon, projeler ve ürünler',
    account: 'Profilim', admin: 'Platform yönetimi', language: 'Dil', switchLang: 'İngilizceye geç', logout: 'Çıkış', beta: 'beta',
    preview: 'önizleme', deprecated: 'kullanımdan kalkıyor', loadError: 'Ürün listesi yüklenemedi.',
    retry: 'Tekrar dene', loading: 'Yükleniyor…', productMenu: 'Bu ürün', other: 'Diğer ürünler',
    project: 'Proje', projects: 'Projeleriniz', chooseProject: 'Proje seçin', noProject: 'Atanmış proje yok',
    switching: 'Geçiliyor…', switchFail: 'Proje değiştirilemedi. Tekrar deneyin.', role: 'Rol', roles: 'Roller',
    org: 'Organizasyon', orgs: 'Organizasyonlarınız', chooseOrg: 'Organizasyon seçin', orgSettings: 'Organizasyon ayarları',
    orgSwitchFail: 'Organizasyon değiştirilemedi. Tekrar deneyin.', context: 'Çalışma bağlamı',
  },
  en: {
    open: 'AI Probe products', title: 'AI Probe', yours: 'Your products', discover: 'Discover',
    request: 'Request access', noAccess: 'No access', current: 'You are here',
    stUp: 'Running', stStopped: 'Stopped', stStarting: 'Starting…', start: 'Start',
    home: 'AI Probe home', homeSub: 'Organization, projects and products',
    account: 'My profile', admin: 'Platform admin', language: 'Language', switchLang: 'Switch to Turkish', logout: 'Sign out', beta: 'beta',
    preview: 'preview', deprecated: 'deprecated', loadError: 'Could not load products.',
    retry: 'Retry', loading: 'Loading…', productMenu: 'This product', other: 'Other products',
    project: 'Project', projects: 'Your projects', chooseProject: 'Select a project', noProject: 'No assigned project',
    switching: 'Switching…', switchFail: 'Could not switch project. Try again.', role: 'Role', roles: 'Roles',
    org: 'Organization', orgs: 'Your organizations', chooseOrg: 'Select an organization', orgSettings: 'Organization settings',
    orgSwitchFail: 'Could not switch organization. Try again.', context: 'Working context',
  },
};
/** Ortak etiket sözlüğü (salt okunur kopya). */
export const LABELS = JSON.parse(JSON.stringify(I18N));

// Yedek değerler TP görsel dili (packages/design-tokens/tokens.css 2.0.0). Sayfa --aip-* tanımlarsa onlar kazanır.
const CSS = `
:host { position: relative; display: inline-flex; align-items: center; gap: 6px; vertical-align: middle;
  font-family: var(--aip-font, "Inter Variable", Inter, system-ui, sans-serif); color-scheme: dark;
  --_bg: var(--aip-surface, #0e0e1c); --_bg2: var(--aip-surface-2, #15152a); --_bd: var(--aip-border, #2e2e58);
  --_tx: var(--aip-text, #f0f0ff); --_tx2: var(--aip-text-2, #94a3b8); --_mut: var(--aip-muted, #8590a6);
  --_acc: var(--aip-accent, #818cf8); --_focus: var(--aip-focus, #a5b4fc); --_tint: var(--aip-tint-12, rgb(99 102 241 / .12));
  --_warn: var(--aip-warn, #fbbf24); --_warnbg: var(--aip-warn-bg, rgb(251 191 36 / .12));
  --_ok: var(--aip-ok, #34d399); --_okbg: var(--aip-ok-bg, rgb(52 211 153 / .12));
  --_ai: var(--aip-ai, #c084fc); --_aibg: var(--aip-ai-bg, rgb(192 132 252 / .12));
  --_sh: var(--aip-shadow-lg, 0 8px 32px rgb(0 0 0 / .55)); }
:host([data-aip-tema="light"]) { color-scheme: light;
  --_bg: var(--aip-surface, #ffffff); --_bg2: var(--aip-surface-2, #f2f4f8); --_bd: var(--aip-border, #e4e7ed);
  --_tx: var(--aip-text, #0f1117); --_tx2: var(--aip-text-2, #4b5263); --_mut: var(--aip-muted, #5f6678);
  --_acc: var(--aip-accent, #4f46e5); --_focus: var(--aip-focus, #4f46e5); --_tint: var(--aip-tint-12, #eef2ff);
  --_warn: var(--aip-warn, #92400e); --_warnbg: var(--aip-warn-bg, #fdf3e7);
  --_ok: var(--aip-ok, #065f46); --_okbg: var(--aip-ok-bg, #e6f2ee);
  --_ai: var(--aip-ai, #7e22ce); --_aibg: var(--aip-ai-bg, #f5edfc);
  --_sh: var(--aip-shadow-lg, 0 10px 32px rgb(15 17 23 / .14), 0 2px 6px rgb(15 17 23 / .06)); }
:host([hidden]) { display: none; }
* { box-sizing: border-box; }
.probe { display: none; color: var(--aip-surface, transparent); }
:focus-visible { outline: 2px solid var(--_focus); outline-offset: 2px; }
.trigger { display: inline-grid; place-items: center; width: 40px; height: 40px; border-radius: 10px;
  border: 1px solid transparent; background: transparent; color: var(--_tx2); cursor: pointer; padding: 0; }
.trigger:hover, .trigger[aria-expanded="true"] { background: var(--_tint); color: var(--_tx); }
.trigger svg { width: 20px; height: 20px; }
.panel { position: absolute; right: 0; top: calc(100% + 8px); z-index: var(--aip-z-popover, 1000);
  width: min(352px, calc(100vw - 24px)); max-height: min(80vh, 640px); overflow: auto; overscroll-behavior: contain;
  background: var(--_bg); color: var(--_tx); border: 1px solid var(--_bd); border-radius: 12px;
  box-shadow: var(--_sh); padding: 6px; font-size: 14px; line-height: 1.4; text-align: left; }
:host([align="left"]) .panel { right: auto; left: 0; }
.panel[hidden] { display: none; }
.head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; padding: 8px 10px 6px; }
.head strong { font-size: 15px; font-weight: 650; }
.who { color: var(--_mut); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60%; }
/* Bölüm etiketleri başlık öğesi değil (sayfanın başlık hiyerarşisini bozmasın); gruplar aria-labelledby ile adlanır. */
.sec { margin: 10px 10px 4px; font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--_mut); }
ul { list-style: none; margin: 0; padding: 0; }
.item { display: flex; align-items: center; gap: 10px; min-height: 48px; padding: 8px 10px; border-radius: 10px; color: inherit; text-decoration: none; }
a.item:hover { background: var(--_tint); }
.item img { width: 28px; height: 28px; flex: none; border-radius: 6px; }
.meta { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.name { font-weight: 600; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.sub { color: var(--_mut); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cur { background: var(--_tint); }
.cur .sub { color: var(--_tx2); }
.badge { font-size: 10px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; padding: 1px 6px;
  border-radius: 999px; border: 1px solid var(--_bd); color: var(--_tx2); }
.badge.beta, .badge.preview { color: var(--_ai); background: var(--_aibg); border-color: transparent; }
.end { display: inline-flex; align-items: center; gap: 6px; flex: none; }
.chip { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
.chip::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.chip.ok { color: var(--_ok); background: var(--_okbg); }
.chip.warn { color: var(--_warn); background: var(--_warnbg); }
.chip.busy::before { animation: aip-pulse 1.2s ease-in-out infinite; }
@keyframes aip-pulse { 50% { opacity: .3; } }
@media (prefers-reduced-motion: reduce) { .chip.busy::before { animation: none; } }
.act { font-size: 12px; font-weight: 600; color: var(--_acc); white-space: nowrap; text-decoration: none; padding: 4px 8px;
  border-radius: 8px; border: 1px solid var(--_bd); }
a.act:hover { background: var(--_tint); }
.lock { width: 12px; height: 12px; flex: none; color: var(--_mut); }
.discover .item img { filter: grayscale(1); opacity: .7; }
.discover .item:hover img, .discover .item:focus-within img { filter: none; opacity: 1; }
.req { color: var(--_acc); font-size: 12px; font-weight: 600; white-space: nowrap; }
.sep { height: 1px; background: var(--_bd); margin: 6px 4px; border: 0; }
.slot { padding: 2px 4px; }
.homerow { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 10px; color: inherit; text-decoration: none; }
.homerow:hover { background: var(--_tint); }
.homerow .hic { display: inline-grid; place-items: center; width: 28px; height: 28px; flex: none; border-radius: 8px;
  background: var(--_bg2); border: 1px solid var(--_bd); color: var(--_acc); }
.homerow .hic svg, .homerow .arr { width: 16px; height: 16px; }
.homerow .arr { color: var(--_mut); flex: none; }
.links form { margin: 0; }
.links a, .links button { display: flex; width: 100%; min-height: 40px; align-items: center; justify-content: space-between; padding: 8px 10px; border-radius: 10px;
  color: inherit; text-decoration: none; background: none; border: 0; font: inherit; cursor: pointer; text-align: left; }
.links a:hover, .links button:hover { background: var(--_tint); }
.lang { display: inline-flex; gap: 2px; border: 1px solid var(--_bd); border-radius: 8px; padding: 2px; }
.lang span { padding: 0 6px; border-radius: 6px; font-size: 12px; }
.lang span[aria-current="true"] { background: var(--_tint); font-weight: 700; }
.msg { padding: 12px 10px; color: var(--_mut); }
.msg button { margin-left: 6px; font: inherit; color: var(--_acc); background: none; border: 0; cursor: pointer; text-decoration: underline; }
.ctxsep { color: var(--_mut); font-size: 14px; }
.ctxsep[hidden] { display: none; }
.proj, .orgb { display: inline-flex; align-items: center; gap: 6px; height: 36px; max-width: 320px; min-width: 0; padding: 0 10px;
  border-radius: 10px; border: 1px solid var(--_bd); background: transparent; color: var(--_tx); font: inherit; font-size: 13px;
  cursor: pointer; white-space: nowrap; }
.orgb { max-width: 200px; }
.proj[hidden], .orgb[hidden] { display: none; }
.proj:hover, .proj[aria-expanded="true"], .orgb:hover, .orgb[aria-expanded="true"] { background: var(--_tint); }
.proj .porg { color: var(--_mut); overflow: hidden; text-overflow: ellipsis; max-width: 120px; }
.proj .pdot { color: var(--_mut); }
.proj .pname, .orgb .oname { font-weight: 600; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.proj svg, .orgb svg { width: 12px; height: 12px; flex: none; color: var(--_mut); }
.proj.warn { color: var(--_warn); background: var(--_warnbg); border-color: transparent; cursor: default; }
.proj[aria-busy="true"], .orgb[aria-busy="true"] { opacity: .7; cursor: progress; }
.plist { right: 48px; width: min(320px, calc(100vw - 24px)); }
.olist { right: auto; left: 0; width: min(300px, calc(100vw - 24px)); }
.plist [role="listbox"] { outline: none; }
.plist [role="listbox"]:focus-visible { outline: 2px solid var(--_focus); outline-offset: 2px; border-radius: 10px; }
.grp { margin: 8px 10px 2px; font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--_mut); }
.opt { display: flex; align-items: center; gap: 10px; min-height: 40px; padding: 8px 10px; border-radius: 10px; cursor: pointer; }
.opt:hover, .opt.active { background: var(--_tint); }
.opt.active { box-shadow: inset 0 0 0 1px var(--_focus); }
.opt.active .sub, .mi:focus .sub, .mi:hover .sub { color: var(--_tx2); }
.chk { width: 16px; flex: none; color: var(--_acc); font-weight: 700; text-align: center; }
.mi { display: flex; width: 100%; align-items: center; gap: 10px; min-height: 40px; padding: 8px 10px; border-radius: 10px; border: 0;
  background: none; color: inherit; font: inherit; text-align: left; cursor: pointer; text-decoration: none; }
.mi:hover, .mi:focus { background: var(--_tint); }
.mi:focus-visible { outline: 2px solid var(--_focus); outline-offset: -2px; }
.perr { margin: 6px 10px; color: var(--_warn); font-size: 12px; }
.perr[hidden] { display: none; }
@media (max-width: 480px) {
  .proj { max-width: 140px; padding: 0 8px; }
  .orgb { max-width: 104px; padding: 0 8px; }
  .proj .porg, .proj .pdot { display: none; }
  .panel, .plist, .olist { position: fixed; left: 8px; right: 8px; width: auto; top: calc(var(--aip-nav-h, 56px) + 4px);
    max-height: calc(100dvh - var(--aip-nav-h, 56px) - 16px); transform: none !important; }
  .item, .opt, .mi, .links a, .links button { min-height: 44px; }
}
`;

let sheet = null;
function styleFor(shadow) {
  try {
    if (!sheet) { sheet = new CSSStyleSheet(); sheet.replaceSync(CSS); }
    shadow.adoptedStyleSheets = [sheet];
  } catch {
    const s = document.createElement('style');
    s.textContent = CSS;
    shadow.append(s);
  }
}

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'text') el.textContent = v;
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
  return el;
}

function svg(markup) {
  const t = document.createElement('template');
  t.innerHTML = markup; // yalnız bu dosyadaki sabit SVG'ler (kullanıcı verisi yok)
  return t.content.firstChild;
}

function withClass(el, cls) { el.setAttribute('class', cls); return el; }

/** Katalogdaki logo adresi home'un /sdk/ yolundaysa bu home-origin'den yüklenir (yerel geliştirmede de çalışır). */
function logoUrl(url, home) {
  try {
    const u = new URL(url, home);
    if (u.pathname.startsWith('/sdk/')) return safeUrl(u.pathname, home);
  } catch { /* geçersiz */ }
  return safeUrl(url, home);
}

function safeUrl(url, base) {
  try {
    const u = new URL(url, base);
    if (u.protocol === 'https:' || (u.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(u.hostname))) return u.href;
  } catch { /* geçersiz */ }
  return null;
}

/** Aynı köken göreli yol ya da safeUrl (org ayarları bağlantısı). */
function linkUrl(url, base) {
  if (typeof url !== 'string' || !url) return null;
  if (/^\/(?!\/)/.test(url)) return url;
  return safeUrl(url, base);
}

// app_url + launch_path; launch_path yalnız "/x" biçimindeyse (şema: ^/[A-Za-z0-9/_.-]*$) eklenir.
function launchUrl(p) {
  const base = typeof p.app_url === 'string' ? p.app_url.replace(/\/+$/, '') : '';
  const lp = p.launch_path;
  if (!base) return p.app_url;
  return typeof lp === 'string' && /^\/(?!\/)[A-Za-z0-9/_.-]*$/.test(lp) ? base + lp : base;
}

const str = (v) => (v == null ? '' : String(v));

/** Ürünün proje verisini ortak biçime çevirir. enabled:false / geçersiz → null (seçici gizli). */
export function normalizeProjects(d) {
  if (!d || typeof d !== 'object' || d.enabled === false) return null;
  const projects = (Array.isArray(d.projects) ? d.projects : [])
    .filter((p) => p && typeof p === 'object')
    .map((p) => ({
      id: str(p.id ?? p.pid), name: str(p.name || p.code || p.id || p.pid), org: str(p.org ?? p.org_name), oid: str(p.oid ?? p.org_id),
      roles: Array.isArray(p.roles) ? p.roles.filter((r) => typeof r === 'string') : [],
    }))
    .filter((p) => p.id);
  const a = d.activeId ?? d.active_id ?? (d.active && typeof d.active === 'object' ? (d.active.id ?? d.active.pid) : d.active);
  const labels = d.roleLabels || d.role_labels;
  return { projects, activeId: projects.some((p) => p.id === str(a)) ? str(a) : null,
    roleLabels: labels && typeof labels === 'object' ? labels : {} };
}

/** Organizasyon verisini ortak biçime çevirir. enabled:false / boş / geçersiz → null (seçici gizli). */
export function normalizeOrgs(d) {
  if (!d || typeof d !== 'object' || d.enabled === false) return null;
  const list = Array.isArray(d) ? d : Array.isArray(d.orgs) ? d.orgs : [];
  const orgs = list.filter((o) => o && typeof o === 'object')
    .map((o) => ({ id: str(o.id ?? o.oid), name: str(o.name || o.id || o.oid), role: str(o.role_label ?? o.roleLabel ?? o.role),
      settingsUrl: typeof (o.settings_url ?? o.settingsUrl) === 'string' ? (o.settings_url ?? o.settingsUrl) : null }))
    .filter((o) => o.id);
  if (!orgs.length) return null;
  const a = Array.isArray(d) ? null
    : d.activeId ?? d.active_id ?? d.active_oid ?? (d.active && typeof d.active === 'object' ? (d.active.id ?? d.active.oid) : d.active);
  const tpl = Array.isArray(d) ? null : (d.settingsUrl ?? d.settings_url);
  return { orgs, activeId: orgs.some((o) => o.id === str(a)) ? str(a) : (orgs.length === 1 ? orgs[0].id : null),
    settingsUrl: typeof tpl === 'string' ? tpl : null };
}

/** "rgb(…)" / "rgba(…)" / "color(srgb …)" → 'dark' | 'light' | null (saydam/çözülemedi). */
export function themeOfColor(c) {
  if (typeof c !== 'string') return null;
  let r; let g; let b; let a = 1;
  let m = c.match(/^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/);
  if (m) { [r, g, b] = [m[1], m[2], m[3]].map((x) => Number(x) / 255); if (m[4] != null) a = m[4].endsWith('%') ? parseFloat(m[4]) / 100 : Number(m[4]); }
  else if ((m = c.match(/^color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+%?))?\s*\)$/))) {
    [r, g, b] = [m[1], m[2], m[3]].map(Number); if (m[4] != null) a = m[4].endsWith('%') ? parseFloat(m[4]) / 100 : Number(m[4]);
  } else return null;
  if (!(a > 0.5) || [r, g, b].some((x) => Number.isNaN(x))) return null;
  const lin = (x) => (x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4);
  const L = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return L < 0.18 ? 'dark' : 'light';
}

/** Ortak tema çerezi (TEMA-SOZLESMESI §2): dark | light | system | null. */
export function readThemeCookie() {
  try {
    const m = document.cookie.match(/(?:^|;\s*)aiprobe_tema=(dark|light|system)(?:;|$)/);
    return m ? m[1] : null;
  } catch { return null; }
}

const CHEVRON = '<svg viewBox="0 0 12 12" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 4.5 6 7.5 9 4.5"/></svg>';
const ICON = '<svg viewBox="0 0 20 20" aria-hidden="true" focusable="false" fill="currentColor">' +
  [3, 10, 17].flatMap((y) => [3, 10, 17].map((x) => `<circle cx="${x}" cy="${y}" r="1.9"/>`)).join('') + '</svg>';
const HOUSE = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v9.5h13V10"/></svg>';
const ARROW = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 6 6 6-6 6"/></svg>';
const LOCK = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>';

let uid = 0;

export class AiprobeSwitcher extends HTMLElement {
  static get observedAttributes() {
    return ['lang', 'product', 'home-origin', 'data-projects-endpoint', 'data-orgs-endpoint', 'links', 'theme', 'admin-url'];
  }

  constructor() {
    super();
    this._id = `aip-sw-${++uid}`;
    this._open = false;
    this._catalog = null;
    this._catalogError = false;
    this._me = undefined; // undefined = yüklenmedi, null = oturum yok/hata
    this._status = null;
    this._statusAt = 0;
    const root = this.attachShadow({ mode: 'open' });
    styleFor(root);
    this._probe = h('span', { class: 'probe', 'aria-hidden': 'true' });
    this._btn = h('button', { class: 'trigger', type: 'button', part: 'trigger', 'aria-haspopup': 'dialog',
      'aria-expanded': 'false', 'aria-controls': `${this._id}-panel`, onclick: () => this.toggle() });
    this._btn.innerHTML = ICON;
    this._panel = h('div', { class: 'panel', part: 'panel', id: `${this._id}-panel`, role: 'dialog',
      'aria-labelledby': `${this._id}-title`, tabindex: '-1', hidden: true, onkeydown: (e) => this._onKey(e), onclick: (e) => this._onClick(e) });
    // Organizasyon seçici: menü düğmesi (aria-haspopup=menu) + menuitemradio satırları.
    this._orgs = null;
    this._oOpen = false;
    this._oBusy = false;
    this._obtn = h('button', { class: 'orgb', type: 'button', part: 'org-trigger', hidden: true, 'aria-haspopup': 'menu',
      'aria-expanded': 'false', 'aria-controls': `${this._id}-olist`, onclick: () => this.toggleOrgs(),
      onkeydown: (e) => { if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); this.openOrgs(e.key === 'ArrowUp' ? 'last' : 'checked'); } } });
    this._omenu = h('div', { role: 'menu', id: `${this._id}-omenu`, onkeydown: (e) => this._onOrgKey(e), onclick: (e) => this._onOrgClick(e) });
    this._oerr = h('p', { class: 'perr', role: 'alert', hidden: true });
    this._olist = h('div', { class: 'panel olist', part: 'org-panel', id: `${this._id}-olist`, hidden: true },
      h('p', { class: 'sec', id: `${this._id}-otitle`, 'aria-hidden': 'true' }), this._omenu, this._oerr);
    this._csep = h('span', { class: 'ctxsep', part: 'ctx-sep', 'aria-hidden': 'true', hidden: true, text: '/' });
    // Proje seçici: düğme + açılır liste (role=listbox, aria-activedescendant ile klavye).
    this._projects = null;
    this._pOpen = false;
    this._pActive = -1;
    this._pBusy = false;
    this._pbtn = h('button', { class: 'proj', type: 'button', part: 'project-trigger', hidden: true, 'aria-haspopup': 'listbox',
      'aria-expanded': 'false', 'aria-controls': `${this._id}-plist`, onclick: () => this.toggleProjects(),
      onkeydown: (e) => { if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); this.openProjects(); } } });
    this._plb = h('ul', { role: 'listbox', id: `${this._id}-plb`, tabindex: '0', 'aria-labelledby': `${this._id}-ptitle`,
      onkeydown: (e) => this._onListKey(e), onclick: (e) => this._onListClick(e) });
    this._perr = h('p', { class: 'perr', role: 'alert', hidden: true });
    this._plist = h('div', { class: 'panel plist', part: 'project-panel', id: `${this._id}-plist`, hidden: true },
      h('p', { class: 'sec', id: `${this._id}-ptitle` }), this._plb, this._perr);
    root.append(this._probe, this._obtn, this._olist, this._csep, this._pbtn, this._plist, this._btn, this._panel);
    this._onDocPointer = (e) => {
      if (e.composedPath().includes(this)) return;
      if (this._open) this.close(false);
      if (this._pOpen) this.closeProjects(false);
      if (this._oOpen) this.closeOrgs(false);
    };
    this._onDocKey = (e) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      if (this._open) { e.preventDefault(); this.close(); }
      if (this._pOpen) { e.preventDefault(); this.closeProjects(); }
      if (this._oOpen) { e.preventDefault(); this.closeOrgs(); }
    };
    this._onThemeChange = () => this._syncTheme();
  }

  get homeOrigin() { return (this.getAttribute('home-origin') || DEFAULT_HOME).replace(/\/+$/, ''); }
  get lang() { const l = (this.getAttribute('lang') || document.documentElement.lang || 'tr').slice(0, 2); return I18N[l] ? l : 'tr'; }
  get me() { return this._me; }
  set me(v) { this._me = v || null; this._meProvided = true; this._render(); }
  /** Etkin tema ('dark' | 'light'); bkz. başlıktaki Tema. */
  get theme() { return this.getAttribute('data-aip-tema') || 'dark'; }

  /** Panelde gösterilecek bağlantılar (`links` özniteliği ya da ürün kipine göre varsayılan). */
  get links() {
    const raw = this.getAttribute('links');
    if (raw != null) return raw.split(/[\s,]+/).filter((k) => LINK_KEYS.includes(k));
    return this.getAttribute('product') === 'home' ? ['account', 'logout'] : LINK_KEYS.slice();
  }

  t(k) { return I18N[this.lang][k] || I18N.tr[k] || k; }

  connectedCallback() {
    this._btn.setAttribute('aria-label', this.t('open'));
    this._btn.title = this.t('open');
    document.addEventListener('pointerdown', this._onDocPointer, true);
    document.addEventListener('keydown', this._onDocKey);
    document.addEventListener('aiprobe:theme', this._onThemeChange);
    if (typeof MutationObserver === 'function') {
      this._themeObs = new MutationObserver(this._onThemeChange);
      this._themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class', 'style'] });
    }
    try {
      this._mq = window.matchMedia('(prefers-color-scheme: light)');
      this._mq.addEventListener('change', this._onThemeChange);
    } catch { this._mq = null; }
    this._syncTheme();
    this._load();
    const g = globalThis.AIProbeSwitcher || {};
    if (!this._projectsProvided && g.projects !== undefined) this.setProjects(g.projects);
    else if (!this._projectsProvided) this._loadProjects();
    if (!this._orgsProvided && g.orgs !== undefined) this.setOrgs(g.orgs);
    else if (!this._orgsProvided) this._loadOrgs();
    this._renderContext();
  }

  disconnectedCallback() {
    document.removeEventListener('pointerdown', this._onDocPointer, true);
    document.removeEventListener('keydown', this._onDocKey);
    document.removeEventListener('aiprobe:theme', this._onThemeChange);
    if (this._themeObs) this._themeObs.disconnect();
    if (this._mq) this._mq.removeEventListener('change', this._onThemeChange);
  }

  attributeChangedCallback(name, oldV, newV) {
    if (oldV === newV || !this.isConnected) return;
    if (name === 'home-origin') { this._catalog = null; this._status = null; this._load(); }
    if (name === 'data-projects-endpoint') { this._loadProjects(); return; }
    if (name === 'data-orgs-endpoint') { this._loadOrgs(); return; }
    if (name === 'theme') { this._syncTheme(); return; }
    this._renderContext();
    this._btn.setAttribute('aria-label', this.t('open'));
    this._btn.title = this.t('open');
    this._render();
  }

  // ─── Tema ─── //

  /** Etkin temayı hesaplar ve host'a `data-aip-tema` olarak yazar (yalnız yedek renkleri seçer). */
  _syncTheme() {
    const forced = this.getAttribute('theme');
    let th = forced === 'dark' || forced === 'light' ? forced : null;
    if (!th) { try { th = themeOfColor(getComputedStyle(this._probe).color); } catch { th = null; } }
    if (!th) {
      const a = document.documentElement.getAttribute('data-theme');
      if (a === 'dark' || a === 'light') th = a;
    }
    if (!th) {
      const c = readThemeCookie();
      if (c === 'dark' || c === 'light') th = c;
      else if (c === 'system') th = this._mq && this._mq.matches ? 'light' : 'dark';
    }
    th = th || 'dark';
    if (this.getAttribute('data-aip-tema') !== th) this.setAttribute('data-aip-tema', th);
  }

  async refresh() {
    this._catalog = null; this._status = null; this._statusAt = 0; if (!this._meProvided) this._me = undefined;
    await Promise.all([this._load(), this._projectsProvided ? null : this._loadProjects(), this._orgsProvided ? null : this._loadOrgs()]);
  }

  /** Açılır paneli görünür alana sığdırır (değiştirici üst çubukta sağ kenarda değilse taşmasın). */
  _fit(el) {
    el.style.transform = '';
    if (getComputedStyle(el).position === 'fixed') return; // dar ekran: panel zaten ekran genişliğinde
    const r = el.getBoundingClientRect();
    const vw = document.documentElement.clientWidth || window.innerWidth;
    let dx = 0;
    if (r.right > vw - 8) dx = vw - 8 - r.right;
    if (r.left + dx < 8) dx = 8 - r.left;
    if (dx) el.style.transform = `translateX(${Math.round(dx)}px)`;
  }

  _closeOthers(keep) {
    if (keep !== 'panel' && this._open) this.close(false);
    if (keep !== 'projects' && this._pOpen) this.closeProjects(false);
    if (keep !== 'orgs' && this._oOpen) this.closeOrgs(false);
  }

  _renderContext() { this._renderOrgs(); this._renderProjects(); }

  // ─── Organizasyon seçici ─── //

  get orgs() { return this._orgs; }

  /** Ürün/Home organizasyonları verir (bkz. normalizeOrgs). Uç (data-orgs-endpoint) okuması bundan sonra yapılmaz. */
  setOrgs(data) {
    this._orgsProvided = true;
    this._orgs = normalizeOrgs(data);
    this._oBusy = false;
    this._renderContext();
  }

  async _loadOrgs() {
    const url = this.getAttribute('data-orgs-endpoint');
    if (!url) return;
    const seq = (this._oSeq = (this._oSeq || 0) + 1);
    let data = null;
    try {
      const r = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      data = r.ok ? await r.json() : null;
    } catch { data = null; }
    if (seq !== this._oSeq || this._orgsProvided) return;
    this._orgs = normalizeOrgs(data);
    this._renderContext();
  }

  _activeOrg() { const d = this._orgs; return d ? d.orgs.find((o) => o.id === d.activeId) || null : null; }

  _orgSettingsUrl(o) {
    if (!o) return null;
    const raw = o.settingsUrl || (this._orgs.settingsUrl ? this._orgs.settingsUrl.replace('{oid}', encodeURIComponent(o.id)) : null);
    return linkUrl(raw, this.homeOrigin);
  }

  toggleOrgs() { this._oOpen ? this.closeOrgs() : this.openOrgs(); }

  openOrgs(focus = 'checked') {
    if (this._oOpen || this._oBusy || !this._orgs) return;
    this._closeOthers('orgs');
    this._oOpen = true;
    this._oerr.hidden = true;
    this._olist.hidden = false;
    this._obtn.setAttribute('aria-expanded', 'true');
    this._renderOrgs();
    this._fit(this._olist);
    const items = this._orgItems();
    const target = focus === 'last' ? items[items.length - 1]
      : items.find((i) => i.getAttribute('aria-checked') === 'true') || items[0];
    if (target) target.focus();
  }

  closeOrgs(restoreFocus = true) {
    if (!this._oOpen) return;
    this._oOpen = false;
    this._olist.hidden = true;
    this._obtn.setAttribute('aria-expanded', 'false');
    if (restoreFocus) this._obtn.focus();
  }

  _orgItems() { return [...this._omenu.querySelectorAll('[role^="menuitem"]')]; }

  _onOrgKey(e) {
    const items = this._orgItems();
    if (!items.length) return;
    const i = items.indexOf(this.shadowRoot.activeElement);
    let n = i;
    if (e.key === 'ArrowDown') n = (i + 1) % items.length;
    else if (e.key === 'ArrowUp') n = (i - 1 + items.length) % items.length;
    else if (e.key === 'Home') n = 0;
    else if (e.key === 'End') n = items.length - 1;
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.closeOrgs(); return; }
    else if (e.key === 'Tab') { this.closeOrgs(false); return; }
    else if (e.key === ' ' && items[i] && items[i].tagName === 'A') { e.preventDefault(); items[i].click(); return; }
    else if (e.key.length === 1 && /\S/.test(e.key)) {
      const k = e.key.toLocaleLowerCase(this.lang);
      for (let s = 1; s <= items.length; s++) {
        const j = (i + s) % items.length;
        if (items[j].textContent.trim().toLocaleLowerCase(this.lang).startsWith(k)) { n = j; break; }
      }
    } else return;
    e.preventDefault();
    if (items[n]) items[n].focus();
  }

  _onOrgClick(e) {
    const it = e.composedPath().find((n) => n instanceof HTMLElement && n.dataset && n.dataset.oid);
    if (it) { e.preventDefault(); this._selectOrg(it.dataset.oid); return; }
    const a = e.composedPath().find((n) => n instanceof HTMLAnchorElement && n.dataset && n.dataset.nav);
    if (!a || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const ev = new CustomEvent('aiprobe:navigate', { bubbles: true, composed: true, cancelable: true,
      detail: { productId: this.getAttribute('product'), url: a.href, kind: a.dataset.nav } });
    if (!this.dispatchEvent(ev)) { e.preventDefault(); return; }
    this.closeOrgs(false);
  }

  async _selectOrg(oid) {
    const d = this._orgs;
    if (!d || !oid || this._oBusy) return;
    if (oid === d.activeId) { this.closeOrgs(); return; }
    const ev = new CustomEvent('aiprobe:org-change', { bubbles: true, composed: true, cancelable: true, detail: { oid } });
    if (!this.dispatchEvent(ev)) { this.closeOrgs(); return; }
    const url = this.getAttribute('data-org-switch-endpoint');
    if (!url) { d.activeId = oid; this.closeOrgs(); this._renderContext(); return; }
    this._oBusy = true;
    this.closeOrgs();
    this._renderOrgs();
    const headers = { 'Content-Type': 'application/json', Accept: 'application/json' };
    const csrf = this._me && typeof this._me.csrf_token === 'string' ? this._me.csrf_token : '';
    if (csrf) headers['X-CSRF-Token'] = csrf;
    let ok = false;
    try {
      const r = await fetch(url, { method: 'PUT', credentials: 'same-origin', headers, body: JSON.stringify({ oid }) });
      ok = r.ok;
    } catch { ok = false; }
    if (ok) { location.reload(); return; }
    this._oBusy = false;
    this._renderOrgs();
    this.openOrgs();
    this._oerr.textContent = this.t('orgSwitchFail');
    this._oerr.hidden = false;
  }

  _renderOrgs() {
    const d = this._orgs;
    const b = this._obtn;
    if (!d) { b.hidden = true; this._csep.hidden = true; this.closeOrgs(false); return; }
    b.hidden = false;
    this._csep.hidden = this._pbtn.hidden;
    const t = (k) => this.t(k);
    const act = this._activeOrg();
    b.setAttribute('aria-busy', String(this._oBusy));
    const label = this._oBusy ? t('switching') : act ? act.name : t('chooseOrg');
    b.replaceChildren(h('span', { class: 'oname', part: 'org-name', text: label }));
    b.insertAdjacentHTML('beforeend', CHEVRON);
    const full = act ? `${t('org')}: ${act.name}` : t('chooseOrg');
    b.setAttribute('aria-label', this._oBusy ? t('switching') : full);
    b.title = full + (act && act.role ? ` (${act.role})` : '');
    this._olist.querySelector('.sec').textContent = t('orgs');
    this._omenu.setAttribute('aria-label', t('orgs'));
    if (!this._oOpen) return;
    const keep = this.shadowRoot.activeElement;
    const keepId = keep && keep.dataset ? (keep.dataset.oid || keep.dataset.key) : null;
    const settings = this._orgSettingsUrl(act);
    this._omenu.replaceChildren(...d.orgs.map((o) => {
      const sel = o.id === d.activeId;
      return h('button', { type: 'button', class: 'mi', role: 'menuitemradio', 'aria-checked': String(sel), tabindex: '-1', 'data-oid': o.id },
        h('span', { class: 'chk', 'aria-hidden': 'true', text: sel ? '✓' : '' }),
        h('span', { class: 'meta' }, h('span', { class: 'name', text: o.name }), o.role ? h('span', { class: 'sub', text: o.role }) : null));
    }), settings ? h('hr', { class: 'sep', role: 'separator' }) : null,
    settings ? h('a', { class: 'mi', role: 'menuitem', tabindex: '-1', href: settings, 'data-nav': 'org-settings', 'data-key': 'org-settings' },
      h('span', { class: 'chk', 'aria-hidden': 'true' }), h('span', { class: 'meta', text: t('orgSettings') })) : null);
    if (keepId) {
      const again = this._omenu.querySelector(`[data-oid="${CSS_ESC(keepId)}"], [data-key="${CSS_ESC(keepId)}"]`);
      if (again) again.focus();
    }
  }

  // ─── Proje seçici ─── //

  get projects() { return this._projects; }

  /** Ürün projeleri verir (bkz. normalizeProjects). Uç (data-projects-endpoint) okuması bundan sonra yapılmaz. */
  setProjects(data) {
    this._projectsProvided = true;
    this._projects = normalizeProjects(data);
    this._pBusy = false;
    this._renderContext();
  }

  async _loadProjects() {
    const url = this.getAttribute('data-projects-endpoint');
    if (!url) return;
    const seq = (this._pSeq = (this._pSeq || 0) + 1);
    let data = null;
    try {
      const r = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      data = r.ok ? await r.json() : null;
    } catch { data = null; }
    if (seq !== this._pSeq || this._projectsProvided) return;
    this._projects = normalizeProjects(data);
    this._renderContext();
  }

  /** Görünen projeler (org seçiliyse ona süzülmüş) ve gruplama; klavye sırası = çizim sırası. */
  _projectView() {
    const d = this._projects;
    if (!d) return { list: [], grouped: false };
    let list = d.projects;
    const ao = this._orgs && this._orgs.activeId;
    if (ao && list.some((p) => p.oid)) list = list.filter((p) => p.oid === ao);
    const orgs = [...new Set(list.map((p) => p.org))];
    const grouped = !this._orgs && orgs.length > 1;
    if (grouped) list = orgs.flatMap((o) => list.filter((p) => p.org === o));
    return { list, grouped };
  }

  _roleText(p) {
    const labels = (this._projects && this._projects.roleLabels) || {};
    return p.roles.map((r) => {
      const l = labels[r];
      return (l && typeof l === 'object' ? (l[this.lang] || l.tr) : l) || r;
    }).join(', ');
  }

  toggleProjects() { this._pOpen ? this.closeProjects() : this.openProjects(); }

  openProjects() {
    const d = this._projects;
    const { list } = this._projectView();
    if (this._pOpen || this._pBusy || !d || !list.length) return;
    this._closeOthers('projects');
    this._pOpen = true;
    this._perr.hidden = true;
    this._pActive = Math.max(0, list.findIndex((p) => p.id === d.activeId));
    this._plist.hidden = false;
    this._pbtn.setAttribute('aria-expanded', 'true');
    this._renderProjects();
    this._fit(this._plist);
    this._plb.focus();
  }

  closeProjects(restoreFocus = true) {
    if (!this._pOpen) return;
    this._pOpen = false;
    this._plist.hidden = true;
    this._pbtn.setAttribute('aria-expanded', 'false');
    if (restoreFocus) this._pbtn.focus();
  }

  _onListKey(e) {
    const { list } = this._projectView();
    if (!list.length) return;
    let i = this._pActive;
    if (e.key === 'ArrowDown') i = Math.min(list.length - 1, i + 1);
    else if (e.key === 'ArrowUp') i = Math.max(0, i - 1);
    else if (e.key === 'Home') i = 0;
    else if (e.key === 'End') i = list.length - 1;
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (list[i]) this._selectProject(list[i].id); return; }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.closeProjects(); return; }
    else if (e.key === 'Tab') { this.closeProjects(false); return; }
    else if (e.key.length === 1 && /\S/.test(e.key)) {
      // Yazarak atla: sonraki, adı bu harfle başlayan proje.
      const k = e.key.toLocaleLowerCase(this.lang);
      for (let n = 1; n <= list.length; n++) {
        const j = (i + n) % list.length;
        if (list[j].name.toLocaleLowerCase(this.lang).startsWith(k)) { i = j; break; }
      }
    } else return;
    e.preventDefault();
    this._pActive = i;
    this._renderProjects();
  }

  _onListClick(e) {
    const li = e.composedPath().find((n) => n instanceof HTMLElement && n.getAttribute && n.getAttribute('role') === 'option');
    if (li) this._selectProject(li.dataset.id);
  }

  async _selectProject(pid) {
    const d = this._projects;
    if (!d || !pid || this._pBusy) return;
    if (pid === d.activeId) { this.closeProjects(); return; }
    const ev = new CustomEvent('aiprobe:project-change', { bubbles: true, composed: true, cancelable: true, detail: { pid } });
    if (!this.dispatchEvent(ev)) { this.closeProjects(); return; }
    const url = this.getAttribute('data-project-switch-endpoint');
    if (!url) { d.activeId = pid; this.closeProjects(); this._renderProjects(); return; }
    this._pBusy = true;
    this.closeProjects();
    this._renderProjects();
    const headers = { 'Content-Type': 'application/json', Accept: 'application/json' };
    const csrf = this._me && typeof this._me.csrf_token === 'string' ? this._me.csrf_token : '';
    if (csrf) headers['X-CSRF-Token'] = csrf;
    let ok = false;
    try {
      const r = await fetch(url, { method: 'PUT', credentials: 'same-origin', headers, body: JSON.stringify({ pid }) });
      ok = r.ok;
    } catch { ok = false; }
    if (ok) { location.reload(); return; }
    this._pBusy = false;
    this._renderProjects();
    this.openProjects();
    this._perr.textContent = this.t('switchFail');
    this._perr.hidden = false;
  }

  _renderProjects() {
    const d = this._projects;
    const b = this._pbtn;
    if (!d) { b.hidden = true; this._csep.hidden = true; this.closeProjects(false); return; }
    b.hidden = false;
    this._csep.hidden = this._obtn.hidden;
    const t = (k) => this.t(k);
    const { list, grouped } = this._projectView();
    const act = list.find((p) => p.id === d.activeId);
    const showOrg = !this._orgs;
    b.classList.toggle('warn', !list.length);
    b.setAttribute('aria-busy', String(this._pBusy));
    if (!list.length) {
      b.replaceChildren(h('span', { class: 'pname', text: t('noProject') }));
      b.setAttribute('aria-disabled', 'true');
      b.setAttribute('aria-label', t('noProject'));
      b.removeAttribute('title');
      this.closeProjects(false);
      return;
    }
    b.removeAttribute('aria-disabled');
    const label = this._pBusy ? t('switching') : act ? act.name : t('chooseProject');
    b.replaceChildren(...(showOrg && act && act.org && !this._pBusy ? [h('span', { class: 'porg', part: 'project-org', text: act.org }), h('span', { class: 'pdot', part: 'project-sep', text: '·', 'aria-hidden': 'true' })] : []),
      h('span', { class: 'pname', part: 'project-name', text: label }));
    b.insertAdjacentHTML('beforeend', CHEVRON);
    const full = act ? `${t('project')}: ${showOrg && act.org ? `${act.org} · ` : ''}${act.name}` : t('chooseProject');
    b.setAttribute('aria-label', this._pBusy ? t('switching') : full);
    b.title = full + (act && act.roles.length ? ` (${this._roleText(act)})` : '');
    this._plist.querySelector('.sec').textContent = t('projects');
    this._plb.setAttribute('aria-label', t('projects'));
    if (!this._pOpen) return;
    const ai = Math.min(Math.max(this._pActive, 0), list.length - 1);
    const opt = (p, i) => {
      const sel = p.id === d.activeId;
      const roles = this._roleText(p);
      const sub = [grouped || !showOrg ? '' : p.org, roles ? `${t(p.roles.length > 1 ? 'roles' : 'role')}: ${roles}` : ''].filter(Boolean).join(' · ');
      return h('li', { role: 'option', id: `${this._id}-po-${i}`, class: `opt${i === ai ? ' active' : ''}`, 'aria-selected': String(sel), 'data-id': p.id },
        h('span', { class: 'chk', 'aria-hidden': 'true', text: sel ? '✓' : '' }),
        h('span', { class: 'meta' }, h('span', { class: 'name', text: p.name }), sub ? h('span', { class: 'sub', text: sub, title: sub }) : null));
    };
    if (grouped) {
      const kids = [];
      let g = 0;
      list.forEach((p, i) => {
        if (i === 0 || list[i - 1].org !== p.org) {
          const gid = `${this._id}-pg-${g++}`;
          kids.push(h('li', { role: 'presentation' }, h('div', { class: 'grp', id: gid, 'aria-hidden': 'true', text: p.org || '—' }),
            h('ul', { role: 'group', 'aria-labelledby': gid })));
        }
        kids[kids.length - 1].lastChild.append(opt(p, i));
      });
      this._plb.replaceChildren(...kids);
    } else this._plb.replaceChildren(...list.map(opt));
    this._plb.setAttribute('aria-activedescendant', `${this._id}-po-${ai}`);
    const cur = this._plb.querySelector(`#${this._id}-po-${ai}`);
    if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: 'nearest' });
  }

  // ─── Ürün paneli ─── //

  async _load() {
    const jobs = [];
    if (!this._catalog) {
      const url = `${this.homeOrigin}/sdk/products.json?v=${VERSION}`;
      // Ağ/CORS hatası (TypeError) eski başlıklı önbellek kopyasından olabilir: önbelleği atlayıp bir kez daha dene.
      jobs.push(fetch(url, { credentials: 'omit' })
        .catch(() => fetch(url, { credentials: 'omit', cache: 'reload' }))
        .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
        .then((d) => { this._catalog = Array.isArray(d) ? d : []; this._catalogError = false; })
        .catch(() => { this._catalogError = true; }));
    }
    if (this._me === undefined && !this._meProvided) {
      const meUrl = this.getAttribute('me-url') || '/auth/me';
      jobs.push(fetch(meUrl, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => { if (!this._meProvided) this._me = d; })
        .catch(() => { if (!this._meProvided) this._me = null; }));
    }
    await Promise.all(jobs);
    this._render();
  }

  async _loadStatus() {
    if (this._status && Date.now() - this._statusAt < STATUS_TTL_MS) return;
    try {
      const r = await fetch(`${this.homeOrigin}/api/v1/status`, { credentials: 'omit' });
      this._status = r.ok ? ((await r.json()).products || {}) : {};
    } catch { this._status = {}; }
    this._statusAt = Date.now();
    this._render();
  }

  toggle() { this._open ? this.close() : this.open(); }

  open() {
    if (this._open) return;
    this._closeOthers('panel');
    this._syncTheme();
    this._open = true;
    this._panel.hidden = false;
    this._btn.setAttribute('aria-expanded', 'true');
    if (!this._catalog) this._load();
    this._loadStatus();
    this._render();
    this._fit(this._panel);
    // Katalog henüz yoksa paneli odakla; veri gelince ilk ürüne geçilir (_render).
    requestAnimationFrame(() => ((this._catalog && this._focusables()[0]) || this._panel).focus());
  }

  close(restoreFocus = true) {
    if (!this._open) return;
    this._open = false;
    this._panel.hidden = true;
    this._btn.setAttribute('aria-expanded', 'false');
    if (restoreFocus) this._btn.focus();
  }

  /** Erişim: 'yes' | 'no' | 'unknown'. me.products (kod→roller; v1.6: diğer ürünler []) varsa kesin; yoksa yalnız bu ürün bilinir. */
  _access(p) {
    const me = this._me;
    if (!me) return 'unknown';
    // v1.6: anahtar var = erişim var (diğer ürünlerin rol listesi boş gelir; rolsüz ürünler hiç yazılmaz).
    if (me.products && typeof me.products === 'object') {
      return Object.prototype.hasOwnProperty.call(me.products, p.code) && Array.isArray(me.products[p.code]) ? 'yes' : 'no';
    }
    if (me.product === p.id) return (me.roles || []).length ? 'yes' : 'no';
    return 'unknown';
  }

  _focusables() {
    const out = [];
    const walk = (node) => {
      for (const el of node.children) {
        if (el.tagName === 'SLOT') { el.assignedElements({ flatten: true }).forEach((a) => { if (isFocusable(a)) out.push(a); walk(a); }); continue; }
        if (isFocusable(el)) out.push(el);
        walk(el);
      }
    };
    walk(this._panel);
    return out;
  }

  _onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.close(); return; }
    const items = this._focusables();
    if (!items.length) return;
    const active = this._activeEl();
    const i = items.indexOf(active);
    if (e.key === 'Tab') {
      if (e.shiftKey && (i <= 0)) { e.preventDefault(); items[items.length - 1].focus(); }
      else if (!e.shiftKey && i === items.length - 1) { e.preventDefault(); items[0].focus(); }
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const n = e.key === 'ArrowDown' ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
      items[n].focus();
    } else if (e.key === 'Home' || e.key === 'End') {
      e.preventDefault();
      items[e.key === 'Home' ? 0 : items.length - 1].focus();
    }
  }

  _activeEl() { return this.shadowRoot.activeElement || document.activeElement; }

  _onClick(e) {
    const a = e.composedPath().find((n) => n instanceof HTMLAnchorElement && n.dataset && n.dataset.nav);
    if (!a) return;
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return; // yeni sekme: mevcut sayfa korunur
    const ev = new CustomEvent('aiprobe:navigate', {
      bubbles: true, composed: true, cancelable: true,
      detail: { productId: a.dataset.product || null, url: a.href, kind: a.dataset.nav },
    });
    if (!this.dispatchEvent(ev)) { e.preventDefault(); return; }
    this.close(false);
  }

  _setLang(lang) {
    this.setAttribute('lang', lang);
    this.dispatchEvent(new CustomEvent('aiprobe:lang', { bubbles: true, composed: true, detail: { lang } }));
    requestAnimationFrame(() => { const b = this.shadowRoot.querySelector('[data-lang-toggle]'); if (b) b.focus(); });
  }

  _productRow(p, access, isCurrent) {
    const t = (k) => this.t(k);
    const home = this.homeOrigin;
    const st = (this._status || {})[p.id];
    const appUrl = safeUrl(launchUrl(p), home);
    const logo = logoUrl(p.logo_url, home);
    const badge = ['beta', 'preview', 'deprecated'].includes(p.status) ? h('span', { class: `badge ${p.status}`, text: t(p.status) }) : null;
    const tagline = (p.tagline && (p.tagline[this.lang] || p.tagline.tr)) || '';
    const body = (sub, locked) => [logo ? h('img', { src: logo, alt: '', width: 28, height: 28, loading: 'lazy' }) : null,
      h('span', { class: 'meta' }, h('span', { class: 'name' }, p.name, badge, locked ? withClass(svg(LOCK), 'lock') : null),
        h('span', { class: 'sub', text: sub }))];

    if (access === 'no') {
      // Durum: erişim yok (kilit + "Erişim yok" alt satırı) · eylem: Erişim iste.
      const url = `${home}/no-access?product=${encodeURIComponent(p.id)}`;
      const row = h('a', { class: 'item', href: url, 'data-nav': 'request-access', 'data-product': p.id, 'data-key': `req:${p.id}` },
        ...body(`${t('noAccess')}${tagline ? ` · ${tagline}` : ''}`, true), h('span', { class: 'req', text: t('request') }));
      return h('li', {}, row);
    }
    const onDemand = p.availability === 'on_demand';
    const down = onDemand && (st === 'stopped' || st === 'starting');
    const sub = isCurrent ? t('current') : tagline;
    if (down && access === 'yes') {
      const starting = st === 'starting';
      const chip = h('span', { class: `chip warn${starting ? ' busy' : ''}`, text: starting ? t('stStarting') : t('stStopped') });
      const action = starting ? null : h('a', { class: 'act', href: `${home}/?start=${encodeURIComponent(p.id)}`, 'data-nav': 'start',
        'data-product': p.id, 'data-key': `start:${p.id}`, 'aria-label': `${p.name}: ${t('stStopped')} · ${t('start')}`, text: t('start') });
      return h('li', {}, h('div', { class: `item${isCurrent ? ' cur' : ''}` }, ...body(sub), h('span', { class: 'end' }, chip, action)));
    }
    const chip = onDemand && st === 'up' ? h('span', { class: 'chip ok', text: t('stUp') }) : null;
    if (!appUrl) return h('li', {}, h('div', { class: 'item' }, ...body(sub), chip));
    return h('li', {}, h('a', { class: `item${isCurrent ? ' cur' : ''}`, href: appUrl, 'data-nav': 'product', 'data-product': p.id, 'data-key': `app:${p.id}`,
      'aria-current': isCurrent ? 'page' : null }, ...body(sub), chip));
  }

  /** Adlandırılmış bölüm (role=group + görünür etiket). */
  _section(key, label, body) {
    const id = `${this._id}-s-${key}`;
    return h('div', { class: key === 'discover' ? 'discover' : null, role: 'group', 'aria-labelledby': id },
      h('p', { class: 'sec', id, text: label }), body);
  }

  _render() {
    if (!this._open) return;
    const t = (k) => this.t(k);
    const home = this.homeOrigin;
    const current = this.getAttribute('product');
    const links = this.links;
    const panel = this._panel;
    const keepFocus = this._activeEl();
    const keepKey = keepFocus && keepFocus.dataset ? (keepFocus.dataset.key || null) : null;
    panel.replaceChildren();

    const me = this._me;
    panel.append(h('div', { class: 'head' }, h('strong', { id: `${this._id}-title`, text: t('title') }),
      me && me.email ? h('span', { class: 'who', text: me.email, title: me.email }) : null));

    // Ürünlerde (Home dışında) Home'a dönüş en üstte.
    if (links.includes('home') && current !== 'home') {
      const a = h('a', { class: 'homerow', href: `${home}/`, 'data-nav': 'home', 'data-key': 'home' },
        h('span', { class: 'hic' }, svg(HOUSE)),
        h('span', { class: 'meta' }, h('span', { class: 'name', text: t('home') }), h('span', { class: 'sub', text: t('homeSub') })));
      a.append(withClass(svg(ARROW), 'arr'));
      panel.append(a, h('hr', { class: 'sep' }));
    }

    if (this._catalogError && !this._catalog) {
      panel.append(h('p', { class: 'msg' }, t('loadError'),
        h('button', { type: 'button', 'data-key': 'retry', onclick: () => this.refresh(), text: t('retry') })));
    } else if (!this._catalog) {
      panel.append(h('p', { class: 'msg', role: 'status', text: t('loading') }));
    } else {
      const rows = this._catalog.filter((p) => p.status !== 'hidden' || this._access(p) === 'yes');
      const mine = rows.filter((p) => this._access(p) !== 'no');
      const other = rows.filter((p) => this._access(p) === 'no');
      if (mine.length) {
        panel.append(this._section('mine', me && me.products ? t('yours') : t('other'),
          h('ul', {}, mine.map((p) => this._productRow(p, this._access(p), p.id === current)))));
      }
      if (other.length) {
        panel.append(this._section('discover', t('discover'),
          h('ul', {}, other.map((p) => this._productRow(p, 'no', p.id === current)))));
      }
    }

    if (this.querySelector('[slot="product-menu"]')) {
      panel.append(h('hr', { class: 'sep' }), this._section('slot', t('productMenu'),
        h('div', { class: 'slot' }, h('slot', { name: 'product-menu' }))));
    }

    const accountUrl = this.getAttribute('account-url') || `${home}/account`;
    const logoutUrl = this.getAttribute('logout-url') || '/auth/logout';
    const adminUrl = this.getAttribute('admin-url');
    const csrf = me && typeof me.csrf_token === 'string' ? me.csrf_token : '';
    const postLogout = (this.getAttribute('logout-method') || 'post').toLowerCase() === 'post' && csrf;
    const other = this.lang === 'tr' ? 'en' : 'tr';
    const logout = postLogout
      ? h('form', { method: 'post', action: logoutUrl },
        h('input', { type: 'hidden', name: 'csrf_token', value: csrf }),
        h('button', { type: 'submit', 'data-nav-form': 'logout', 'data-key': 'logout', text: t('logout') }))
      : h('a', { href: logoutUrl, 'data-nav': 'logout', 'data-key': 'logout', text: t('logout') });
    const bottom = [
      links.includes('account') ? h('a', { href: accountUrl, 'data-nav': 'account', 'data-key': 'account', text: t('account') }) : null,
      links.includes('admin') && adminUrl ? h('a', { href: adminUrl, 'data-nav': 'admin', 'data-key': 'admin', text: t('admin') }) : null,
      // Erişilebilir ad = görünür metin ("Dil TR EN"); eylem açıklamada (title) — WCAG 2.5.3 Label in Name.
      links.includes('lang') ? h('button', { type: 'button', 'data-lang-toggle': true, 'data-key': 'lang',
        title: t('switchLang'), onclick: () => this._setLang(other) },
      h('span', { text: t('language') }), ' ',
      h('span', { class: 'lang' },
        h('span', { 'aria-current': String(this.lang === 'tr'), text: 'TR' }), ' ',
        h('span', { 'aria-current': String(this.lang === 'en'), text: 'EN' }))) : null,
      links.includes('logout') ? logout : null,
    ].filter(Boolean);
    if (bottom.length) panel.append(h('hr', { class: 'sep' }), h('div', { class: 'links' }, ...bottom));

    const wasInside = keepFocus && (this.shadowRoot.contains(keepFocus) && keepFocus !== this._btn);
    const again = keepKey && panel.querySelector(`[data-key="${CSS_ESC(keepKey)}"]`);
    if (again) again.focus();
    else if (this._catalog && this.shadowRoot.activeElement === panel) { const f = this._focusables()[0]; if (f) f.focus(); }
    else if (wasInside && !this._panel.contains(this.shadowRoot.activeElement)) (this._focusables()[0] || panel).focus();
  }
}

function CSS_ESC(s) {
  const C = globalThis.CSS; // modüldeki CSS sabiti (stil metni) genel CSS nesnesini gölgeler
  return C && typeof C.escape === 'function' ? C.escape(s) : String(s).replace(/["\\]/g, '\\$&');
}

function isFocusable(el) {
  if (el.hasAttribute('disabled') || el.getAttribute('tabindex') === '-1' || el.hidden) return false;
  if (el.tagName === 'A') return el.hasAttribute('href');
  return ['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName) || el.hasAttribute('tabindex');
}

if (!customElements.get('aiprobe-switcher')) customElements.define('aiprobe-switcher', AiprobeSwitcher);

// Genel API: window.AIProbeSwitcher.setProjects(data) / setOrgs(data) sayfadaki tüm değiştiricilere uygular;
// sonradan bağlanan değiştiriciler de bu veriyi alır. Ürün betiği modül yüklenmeden çalışabilir: önceden
// `window.AIProbeSwitcher = {projects: data, orgs: data}` atanmışsa da kullanılır.
const api = (globalThis.AIProbeSwitcher && typeof globalThis.AIProbeSwitcher === 'object') ? globalThis.AIProbeSwitcher : {};
api.VERSION = VERSION;
api.LABELS = LABELS;
api.setProjects = (data) => {
  api.projects = data;
  document.querySelectorAll('aiprobe-switcher').forEach((el) => { if (typeof el.setProjects === 'function') el.setProjects(data); });
};
api.setOrgs = (data) => {
  api.orgs = data;
  document.querySelectorAll('aiprobe-switcher').forEach((el) => { if (typeof el.setOrgs === 'function') el.setOrgs(data); });
};
globalThis.AIProbeSwitcher = api;
