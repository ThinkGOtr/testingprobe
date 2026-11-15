/*! @aiprobe/switcher — <aiprobe-switcher> ürün değiştirici. Bağımlılık yok, derleme gerekmez.
 *
 * Kullanım:
 *   <script type="module" src="/vendor/switcher-1.1.0.js" integrity="sha384-…"></script>
 *   <aiprobe-switcher product="testing-probe" home-origin="https://home.aiprobe.antreklabs.com" lang="tr">
 *     <div slot="product-menu"><button>Rol değiştir</button></div>
 *   </aiprobe-switcher>
 *
 * Öznitelikler: product, home-origin, me-url (vars. /auth/me), lang (tr|en),
 *               logout-url (vars. /auth/logout), account-url (vars. {home}/account),
 *               logout-method (post|get; vars. post: me.csrf_token varsa form POST, yoksa bağlantı),
 *               admin-url (verilirse "Yönetim" bağlantısı gösterilir)
 * Gizli (status=hidden) ürünler yalnız kullanıcının o üründe rolü varsa listelenir.
 *
 * Proje seçici (1.1.0): ürün projelerini verirse ızgara düğmesinin solunda "Organizasyon · Proje" düğmesi
 * ve açılır liste (role=listbox) gösterilir. Veri iki yoldan gelir:
 *   (a) data-projects-endpoint="/api/projects" → GET (same-origin) ile okunur;
 *   (b) ürün el.setProjects(data) ya da window.AIProbeSwitcher.setProjects(data) çağırır.
 *   data: {enabled?, projects:[{id|pid, name, org|org_name, roles:[…]}], activeId|active_id|active:{id|pid},
 *          roleLabels?:{kod: ad}}. enabled:false ya da null → seçici gizli. Boş liste → "Atanmış proje yok".
 * Seçimde cancelable `aiprobe:project-change` {pid} yayınlanır. preventDefault edilmezse ve
 * data-project-switch-endpoint verilmişse oraya PUT {pid} (JSON; me.csrf_token varsa X-CSRF-Token) gönderilir,
 * başarıda sayfa yenilenir. Uç yoksa seçimi ürün olaydan uygular (ve sayfayı kendisi yeniler).
 *
 * 1.1.0: proje seçici (yukarıda), refresh() proje ucunu da yeniden okur; açılır paneller görünür alana
 *        sığdırılır. Stil kancaları: ::part(project-trigger | project-org | project-sep | project-name | project-panel).
 * 1.0.4: products.json sürüm sorgusuyla (?v=<VERSION>) istenir — her sürüm yeni önbellek anahtarı; ağ/CORS
 *        hatasında bir kez önbelleği atlayarak (cache: 'reload') yeniden denenir (ACAO'suz önbelleğe alınmış
 *        kopya 304'le yeniden kullanılıp CORS hatası veriyordu). Dil düğmesinin erişilebilir adı görünür
 *        metniyle aynı ("Dil TR EN"), eylem title/açıklamada (WCAG 2.5.3).
 * 1.0.3: ürün bağlantısı app_url + launch_path (ör. Agent Probe /app); launch_path yalnız "/" ile
 *        başlayan göreli yol ise eklenir.
 * 1.0.2: erişim = me.products'ta kodun VARLIĞI (sözleşme v1.6: ürün oturumlarında yalnız çağıran ürünün
 *        rolleri gelir, diğer erişilebilir ürünler boş liste `[]`). Eski home yanıtlarıyla da aynı sonuç.
 * 1.0.1: çıkış POST (CSRF) formu; gizli ürünler rol varsa görünür; "Keşfet" satırları soluk değil
 *        (AA kontrast, yalnız logo gri); admin-url; logo adresi home-origin'e göre çözülür.
 * Özellikler:   .me (nesne verilirse me-url çağrılmaz), .refresh(), .setProjects(data), .projects
 * Olaylar:      aiprobe:navigate  {productId, url, kind}  — cancelable; preventDefault gezinmeyi durdurur
 *               aiprobe:lang      {lang}                  — kullanıcı dil değiştirdi (ürün kaydeder)
 *               aiprobe:project-change {pid}              — cancelable; kullanıcı proje seçti
 *
 * "Başlat" (on_demand ürün kapalı): POST /api/v1/products/{id}/start Firebase ID token ister; ürün
 * sayfalarında bu token yoktur. Bu yüzden değiştirici {home}/?start=<id> adresine bağlanır; başlatmayı
 * home sayfası (kullanıcı onayıyla) yapar.
 */

export const VERSION = '1.1.0';
const DEFAULT_HOME = 'https://home.aiprobe.antreklabs.com';
const STATUS_TTL_MS = 30_000;

const I18N = {
  tr: {
    open: 'AI Probe ürünleri', title: 'AI Probe', yours: 'Ürünleriniz', discover: 'Keşfet',
    request: 'Erişim iste', current: 'Buradasınız', stopped: 'Kapalı · Başlat', starting: 'Başlatılıyor…',
    home: 'Başlangıç', account: 'Hesap', admin: 'Yönetim', language: 'Dil', switchLang: 'İngilizceye geç', logout: 'Çıkış', beta: 'beta',
    preview: 'önizleme', deprecated: 'kullanımdan kalkıyor', loadError: 'Ürün listesi yüklenemedi.',
    retry: 'Tekrar dene', loading: 'Yükleniyor…', productMenu: 'Bu ürün', other: 'Diğer ürünler',
    project: 'Proje', projects: 'Projeleriniz', chooseProject: 'Proje seçin', noProject: 'Atanmış proje yok',
    switching: 'Geçiliyor…', switchFail: 'Proje değiştirilemedi. Tekrar deneyin.', role: 'Rol', roles: 'Roller',
  },
  en: {
    open: 'AI Probe products', title: 'AI Probe', yours: 'Your products', discover: 'Discover',
    request: 'Request access', current: 'You are here', stopped: 'Stopped · Start', starting: 'Starting…',
    home: 'Home', account: 'Account', admin: 'Admin', language: 'Language', switchLang: 'Switch to Turkish', logout: 'Sign out', beta: 'beta',
    preview: 'preview', deprecated: 'deprecated', loadError: 'Could not load products.',
    retry: 'Retry', loading: 'Loading…', productMenu: 'This product', other: 'Other products',
    project: 'Project', projects: 'Your projects', chooseProject: 'Select a project', noProject: 'No assigned project',
    switching: 'Switching…', switchFail: 'Could not switch project. Try again.', role: 'Role', roles: 'Roles',
  },
};

const CSS = `
:host { position: relative; display: inline-flex; align-items: center; gap: 6px; vertical-align: middle; font-family: var(--aip-font, system-ui, sans-serif);
  --_bg: var(--aip-surface, #fff); --_bg2: var(--aip-surface-2, #eef0f8); --_bd: var(--aip-border, #d9dbea);
  --_tx: var(--aip-text, #0b0b14); --_tx2: var(--aip-text-2, #3b4252); --_mut: var(--aip-muted, #555d6e);
  --_acc: var(--aip-accent, #4338ca); --_focus: var(--aip-focus, #4f46e5); --_tint: var(--aip-tint-12, rgb(79 70 229 / .1));
  --_warn: var(--aip-warn, #92400e); --_warnbg: var(--aip-warn-bg, rgb(251 191 36 / .16));
  --_ai: var(--aip-ai, #7e22ce); --_aibg: var(--aip-ai-bg, rgb(126 34 206 / .08));
  --_sh: var(--aip-shadow-lg, 0 12px 40px rgb(15 15 40 / .18)); }
@media (prefers-color-scheme: dark) { :host {
  --_bg: var(--aip-surface, #0c0c18); --_bg2: var(--aip-surface-2, #12121f); --_bd: var(--aip-border, #2e2e58);
  --_tx: var(--aip-text, #f0f0ff); --_tx2: var(--aip-text-2, #94a3b8); --_mut: var(--aip-muted, #8590a6);
  --_acc: var(--aip-accent, #818cf8); --_focus: var(--aip-focus, #a5b4fc); --_tint: var(--aip-tint-12, rgb(99 102 241 / .12));
  --_warn: var(--aip-warn, #fbbf24); --_warnbg: var(--aip-warn-bg, rgb(251 191 36 / .08));
  --_ai: var(--aip-ai, #c084fc); --_aibg: var(--aip-ai-bg, rgb(192 132 252 / .12));
  --_sh: var(--aip-shadow-lg, 0 8px 48px rgb(0 0 0 / .6)); } }
* { box-sizing: border-box; }
:focus-visible { outline: 2px solid var(--_focus); outline-offset: 2px; }
.trigger { display: inline-grid; place-items: center; width: 40px; height: 40px; border-radius: 10px;
  border: 1px solid transparent; background: transparent; color: var(--_tx2); cursor: pointer; padding: 0; }
.trigger:hover, .trigger[aria-expanded="true"] { background: var(--_tint); color: var(--_tx); }
.trigger svg { width: 20px; height: 20px; }
.panel { position: absolute; right: 0; top: calc(100% + 8px); z-index: var(--aip-z-popover, 1000);
  width: min(340px, calc(100vw - 24px)); max-height: min(80vh, 640px); overflow: auto;
  background: var(--_bg); color: var(--_tx); border: 1px solid var(--_bd); border-radius: 14px;
  box-shadow: var(--_sh); padding: 8px; font-size: 14px; line-height: 1.4; }
:host([align="left"]) .panel { right: auto; left: 0; }
.panel[hidden] { display: none; }
.head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; padding: 8px 10px 6px; }
.head strong { font-size: 15px; }
.who { color: var(--_mut); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60%; }
h3 { margin: 10px 10px 4px; font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--_mut); }
ul { list-style: none; margin: 0; padding: 0; }
.item { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 10px; color: inherit; text-decoration: none; }
a.item:hover { background: var(--_tint); }
.item img { width: 28px; height: 28px; flex: none; border-radius: 6px; }
.meta { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.name { font-weight: 600; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.sub { color: var(--_mut); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cur { background: var(--_tint); }
.badge { font-size: 10px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; padding: 1px 6px;
  border-radius: 999px; border: 1px solid var(--_bd); color: var(--_tx2); }
.badge.beta, .badge.preview { color: var(--_ai); background: var(--_aibg); border-color: transparent; }
.state { font-size: 12px; font-weight: 600; color: var(--_warn); background: var(--_warnbg); padding: 2px 8px; border-radius: 999px; text-decoration: none; white-space: nowrap; }
a.state:hover { text-decoration: underline; }
.discover .item img { filter: grayscale(1); opacity: .7; }
.discover .item:hover img, .discover .item:focus-within img { filter: none; opacity: 1; }
.req { color: var(--_acc); font-size: 12px; font-weight: 600; white-space: nowrap; }
.sep { height: 1px; background: var(--_bd); margin: 8px 4px; border: 0; }
.slot { padding: 2px 4px; }
.links form { margin: 0; }
.links a, .links button { display: flex; width: 100%; align-items: center; justify-content: space-between; padding: 8px 10px; border-radius: 10px;
  color: inherit; text-decoration: none; background: none; border: 0; font: inherit; cursor: pointer; text-align: left; }
.links a:hover, .links button:hover { background: var(--_tint); }
.lang { display: inline-flex; gap: 2px; border: 1px solid var(--_bd); border-radius: 8px; padding: 2px; }
.lang span { padding: 0 6px; border-radius: 6px; font-size: 12px; }
.lang span[aria-current="true"] { background: var(--_tint); font-weight: 700; }
.msg { padding: 12px 10px; color: var(--_mut); }
.proj { display: inline-flex; align-items: center; gap: 6px; height: 36px; max-width: 320px; min-width: 0; padding: 0 10px;
  border-radius: 10px; border: 1px solid var(--_bd); background: transparent; color: var(--_tx); font: inherit; font-size: 13px;
  cursor: pointer; white-space: nowrap; }
.proj[hidden] { display: none; }
.proj:hover, .proj[aria-expanded="true"] { background: var(--_tint); }
.proj .porg { color: var(--_mut); overflow: hidden; text-overflow: ellipsis; max-width: 120px; }
.proj .pdot { color: var(--_mut); }
.proj .pname { font-weight: 600; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.proj svg { width: 12px; height: 12px; flex: none; color: var(--_mut); }
.proj.warn { color: var(--_warn); background: var(--_warnbg); border-color: transparent; cursor: default; }
.proj[aria-busy="true"] { opacity: .7; cursor: progress; }
.plist { right: 48px; width: min(320px, calc(100vw - 24px)); }
.plist [role="listbox"] { outline: none; }
.plist [role="listbox"]:focus-visible { outline: 2px solid var(--_focus); outline-offset: 2px; border-radius: 10px; }
.opt { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 10px; cursor: pointer; }
.opt:hover, .opt.active { background: var(--_tint); }
.opt.active { box-shadow: inset 0 0 0 1px var(--_focus); }
.opt .chk { width: 16px; flex: none; color: var(--_acc); font-weight: 700; text-align: center; }
.perr { margin: 6px 10px; color: var(--_warn); font-size: 12px; }
.perr[hidden] { display: none; }
@media (max-width: 480px) {
  .proj { max-width: 150px; padding: 0 8px; }
  .proj .porg, .proj .pdot { display: none; }
  .plist { right: 0; }
}
.msg button { margin-left: 6px; font: inherit; color: var(--_acc); background: none; border: 0; cursor: pointer; text-decoration: underline; }
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

// app_url + launch_path; launch_path yalnız "/x" biçimindeyse (şema: ^/[A-Za-z0-9/_.-]*$) eklenir.
function launchUrl(p) {
  const base = typeof p.app_url === 'string' ? p.app_url.replace(/\/+$/, '') : '';
  const lp = p.launch_path;
  if (!base) return p.app_url;
  return typeof lp === 'string' && /^\/(?!\/)[A-Za-z0-9/_.-]*$/.test(lp) ? base + lp : base;
}

/** Ürünün proje verisini ortak biçime çevirir. enabled:false / geçersiz → null (seçici gizli). */
export function normalizeProjects(d) {
  if (!d || typeof d !== 'object' || d.enabled === false) return null;
  const str = (v) => (v == null ? '' : String(v));
  const projects = (Array.isArray(d.projects) ? d.projects : [])
    .filter((p) => p && typeof p === 'object')
    .map((p) => ({
      id: str(p.id ?? p.pid), name: str(p.name || p.code || p.id || p.pid), org: str(p.org ?? p.org_name),
      roles: Array.isArray(p.roles) ? p.roles.filter((r) => typeof r === 'string') : [],
    }))
    .filter((p) => p.id);
  const a = d.activeId ?? d.active_id ?? (d.active && typeof d.active === 'object' ? (d.active.id ?? d.active.pid) : d.active);
  const labels = d.roleLabels || d.role_labels;
  return { projects, activeId: projects.some((p) => p.id === str(a)) ? str(a) : null,
    roleLabels: labels && typeof labels === 'object' ? labels : {} };
}

const CHEVRON = '<svg viewBox="0 0 12 12" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 4.5 6 7.5 9 4.5"/></svg>';

const ICON = '<svg viewBox="0 0 20 20" aria-hidden="true" focusable="false" fill="currentColor">' +
  [3, 10, 17].flatMap((y) => [3, 10, 17].map((x) => `<circle cx="${x}" cy="${y}" r="1.9"/>`)).join('') + '</svg>';

let uid = 0;

export class AiprobeSwitcher extends HTMLElement {
  static get observedAttributes() { return ['lang', 'product', 'home-origin', 'data-projects-endpoint']; }

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
    this._btn = h('button', { class: 'trigger', type: 'button', part: 'trigger', 'aria-haspopup': 'dialog',
      'aria-expanded': 'false', 'aria-controls': `${this._id}-panel`, onclick: () => this.toggle() });
    this._btn.innerHTML = ICON;
    this._panel = h('div', { class: 'panel', part: 'panel', id: `${this._id}-panel`, role: 'dialog',
      'aria-labelledby': `${this._id}-title`, tabindex: '-1', hidden: true, onkeydown: (e) => this._onKey(e), onclick: (e) => this._onClick(e) });
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
      h('h3', { id: `${this._id}-ptitle` }), this._plb, this._perr);
    root.append(this._pbtn, this._plist, this._btn, this._panel);
    this._onDocPointer = (e) => {
      if (e.composedPath().includes(this)) return;
      if (this._open) this.close(false);
      if (this._pOpen) this.closeProjects(false);
    };
    this._onDocKey = (e) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      if (this._open) { e.preventDefault(); this.close(); }
      if (this._pOpen) { e.preventDefault(); this.closeProjects(); }
    };
  }

  get homeOrigin() { return (this.getAttribute('home-origin') || DEFAULT_HOME).replace(/\/+$/, ''); }
  get lang() { const l = (this.getAttribute('lang') || document.documentElement.lang || 'tr').slice(0, 2); return I18N[l] ? l : 'tr'; }
  get me() { return this._me; }
  set me(v) { this._me = v || null; this._meProvided = true; this._render(); }

  t(k) { return I18N[this.lang][k] || I18N.tr[k] || k; }

  connectedCallback() {
    this._btn.setAttribute('aria-label', this.t('open'));
    this._btn.title = this.t('open');
    document.addEventListener('pointerdown', this._onDocPointer, true);
    document.addEventListener('keydown', this._onDocKey);
    this._load();
    const pending = globalThis.AIProbeSwitcher && globalThis.AIProbeSwitcher.projects;
    if (!this._projectsProvided && pending !== undefined) this.setProjects(pending);
    else if (!this._projectsProvided) this._loadProjects();
    this._renderProjects();
  }

  disconnectedCallback() {
    document.removeEventListener('pointerdown', this._onDocPointer, true);
    document.removeEventListener('keydown', this._onDocKey);
  }

  attributeChangedCallback(name, oldV, newV) {
    if (oldV === newV || !this.isConnected) return;
    if (name === 'home-origin') { this._catalog = null; this._status = null; this._load(); }
    if (name === 'data-projects-endpoint') { this._loadProjects(); return; }
    this._renderProjects();
    this._btn.setAttribute('aria-label', this.t('open'));
    this._btn.title = this.t('open');
    this._render();
  }

  async refresh() {
    this._catalog = null; this._status = null; this._statusAt = 0; if (!this._meProvided) this._me = undefined;
    await Promise.all([this._load(), this._projectsProvided ? null : this._loadProjects()]);
  }

  // ─── Proje seçici ─── //

  get projects() { return this._projects; }

  /** Ürün projeleri verir (bkz. normalizeProjects). Uç (data-projects-endpoint) okuması bundan sonra yapılmaz. */
  setProjects(data) {
    this._projectsProvided = true;
    this._projects = normalizeProjects(data);
    this._pBusy = false;
    this._renderProjects();
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
    this._renderProjects();
  }

  _roleText(p) {
    const labels = (this._projects && this._projects.roleLabels) || {};
    return p.roles.map((r) => {
      const l = labels[r];
      return (l && typeof l === 'object' ? (l[this.lang] || l.tr) : l) || r;
    }).join(', ');
  }

  /** Açılır paneli görünür alana sığdırır (değiştirici üst çubukta sağ kenarda değilse taşmasın). */
  _fit(el) {
    el.style.transform = '';
    const r = el.getBoundingClientRect();
    const vw = document.documentElement.clientWidth || window.innerWidth;
    let dx = 0;
    if (r.right > vw - 8) dx = vw - 8 - r.right;
    if (r.left + dx < 8) dx = 8 - r.left;
    if (dx) el.style.transform = `translateX(${Math.round(dx)}px)`;
  }

  toggleProjects() { this._pOpen ? this.closeProjects() : this.openProjects(); }

  openProjects() {
    const d = this._projects;
    if (this._pOpen || this._pBusy || !d || !d.projects.length) return;
    if (this._open) this.close(false);
    this._pOpen = true;
    this._perr.hidden = true;
    this._pActive = Math.max(0, d.projects.findIndex((p) => p.id === d.activeId));
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
    const list = (this._projects && this._projects.projects) || [];
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
    if (!d) { b.hidden = true; this.closeProjects(false); return; }
    b.hidden = false;
    const t = (k) => this.t(k);
    const act = d.projects.find((p) => p.id === d.activeId);
    b.classList.toggle('warn', !d.projects.length);
    b.setAttribute('aria-busy', String(this._pBusy));
    if (!d.projects.length) {
      b.replaceChildren(h('span', { class: 'pname', text: t('noProject') }));
      b.setAttribute('aria-disabled', 'true');
      b.setAttribute('aria-label', t('noProject'));
      b.removeAttribute('title');
      return;
    }
    b.removeAttribute('aria-disabled');
    const label = this._pBusy ? t('switching') : act ? act.name : t('chooseProject');
    b.replaceChildren(...(act && act.org && !this._pBusy ? [h('span', { class: 'porg', part: 'project-org', text: act.org }), h('span', { class: 'pdot', part: 'project-sep', text: '·', 'aria-hidden': 'true' })] : []),
      h('span', { class: 'pname', part: 'project-name', text: label }));
    b.insertAdjacentHTML('beforeend', CHEVRON);
    const full = act ? `${t('project')}: ${act.org ? `${act.org} · ` : ''}${act.name}` : t('chooseProject');
    b.setAttribute('aria-label', this._pBusy ? t('switching') : full);
    b.title = full + (act && act.roles.length ? ` (${this._roleText(act)})` : '');
    this._plist.querySelector('h3').textContent = t('projects');
    this._plb.setAttribute('aria-label', t('projects'));
    if (!this._pOpen) return;
    const ai = Math.min(Math.max(this._pActive, 0), d.projects.length - 1);
    this._plb.replaceChildren(...d.projects.map((p, i) => {
      const sel = p.id === d.activeId;
      const roles = this._roleText(p);
      const sub = [p.org, roles ? `${t(p.roles.length > 1 ? 'roles' : 'role')}: ${roles}` : ''].filter(Boolean).join(' · ');
      return h('li', { role: 'option', id: `${this._id}-po-${i}`, class: `opt${i === ai ? ' active' : ''}`, 'aria-selected': String(sel), 'data-id': p.id },
        h('span', { class: 'chk', 'aria-hidden': 'true', text: sel ? '✓' : '' }),
        h('span', { class: 'meta' }, h('span', { class: 'name', text: p.name }), sub ? h('span', { class: 'sub', text: sub, title: sub }) : null));
    }));
    this._plb.setAttribute('aria-activedescendant', `${this._id}-po-${ai}`);
    const cur = this._plb.children[ai];
    if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: 'nearest' });
  }

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
    if (this._pOpen) this.closeProjects(false);
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
    const body = [logo ? h('img', { src: logo, alt: '', width: 28, height: 28, loading: 'lazy' }) : null,
      h('span', { class: 'meta' }, h('span', { class: 'name' }, p.name, badge),
        h('span', { class: 'sub', text: isCurrent ? t('current') : tagline }))];

    if (access === 'no') {
      const url = `${home}/no-access?product=${encodeURIComponent(p.id)}`;
      return h('li', {}, h('a', { class: 'item', href: url, 'data-nav': 'request-access', 'data-product': p.id, 'data-key': `req:${p.id}` },
        ...body, h('span', { class: 'req', text: t('request') })));
    }
    const down = p.availability === 'on_demand' && (st === 'stopped' || st === 'starting');
    if (down && access === 'yes') {
      const startUrl = `${home}/?start=${encodeURIComponent(p.id)}`;
      const label = st === 'starting' ? t('starting') : t('stopped');
      return h('li', {}, h('div', { class: `item${isCurrent ? ' cur' : ''}` }, ...body,
        h('a', { class: 'state', href: startUrl, 'data-nav': 'start', 'data-product': p.id, 'data-key': `start:${p.id}`, text: label })));
    }
    if (!appUrl) return h('li', {}, h('div', { class: 'item' }, ...body));
    return h('li', {}, h('a', { class: `item${isCurrent ? ' cur' : ''}`, href: appUrl, 'data-nav': 'product', 'data-product': p.id, 'data-key': `app:${p.id}`,
      'aria-current': isCurrent ? 'page' : null }, ...body));
  }

  _render() {
    if (!this._open) return;
    const t = (k) => this.t(k);
    const home = this.homeOrigin;
    const current = this.getAttribute('product');
    const panel = this._panel;
    const keepFocus = this._activeEl();
    const keepKey = keepFocus && keepFocus.dataset ? (keepFocus.dataset.key || null) : null;
    panel.replaceChildren();

    const me = this._me;
    panel.append(h('div', { class: 'head' }, h('strong', { id: `${this._id}-title`, text: t('title') }),
      me && me.email ? h('span', { class: 'who', text: me.email, title: me.email }) : null));

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
        panel.append(h('h3', { text: me && me.products ? t('yours') : t('other') }),
          h('ul', {}, mine.map((p) => this._productRow(p, this._access(p), p.id === current))));
      }
      if (other.length) {
        panel.append(h('div', { class: 'discover' }, h('h3', { text: t('discover') }),
          h('ul', {}, other.map((p) => this._productRow(p, 'no', p.id === current)))));
      }
    }

    if (this.querySelector('[slot="product-menu"]')) {
      panel.append(h('hr', { class: 'sep' }), h('h3', { text: t('productMenu') }),
        h('div', { class: 'slot' }, h('slot', { name: 'product-menu' })));
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
    panel.append(h('hr', { class: 'sep' }), h('div', { class: 'links' },
      h('a', { href: `${home}/`, 'data-nav': 'home', 'data-key': 'home', text: t('home') }),
      h('a', { href: accountUrl, 'data-nav': 'account', 'data-key': 'account', text: t('account') }),
      adminUrl ? h('a', { href: adminUrl, 'data-nav': 'admin', 'data-key': 'admin', text: t('admin') }) : null,
      // Erişilebilir ad = görünür metin ("Dil TR EN"); eylem açıklamada (title) — WCAG 2.5.3 Label in Name.
      h('button', { type: 'button', 'data-lang-toggle': true, 'data-key': 'lang',
        title: t('switchLang'), onclick: () => this._setLang(other) },
      h('span', { text: t('language') }), ' ',
      h('span', { class: 'lang' },
        h('span', { 'aria-current': String(this.lang === 'tr'), text: 'TR' }), ' ',
        h('span', { 'aria-current': String(this.lang === 'en'), text: 'EN' }))),
      logout));

    const wasInside = keepFocus && (this.shadowRoot.contains(keepFocus) && keepFocus !== this._btn);
    const again = keepKey && panel.querySelector(`[data-key="${keepKey}"]`);
    if (again) again.focus();
    else if (this._catalog && this.shadowRoot.activeElement === panel) { const f = this._focusables()[0]; if (f) f.focus(); }
    else if (wasInside && !this._panel.contains(this.shadowRoot.activeElement)) (this._focusables()[0] || panel).focus();
  }
}

function isFocusable(el) {
  if (el.hasAttribute('disabled') || el.getAttribute('tabindex') === '-1' || el.hidden) return false;
  if (el.tagName === 'A') return el.hasAttribute('href');
  return ['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName) || el.hasAttribute('tabindex');
}

if (!customElements.get('aiprobe-switcher')) customElements.define('aiprobe-switcher', AiprobeSwitcher);

// Genel API: window.AIProbeSwitcher.setProjects(data) sayfadaki tüm değiştiricilere uygular; sonradan bağlanan
// değiştiriciler de bu veriyi alır. Ürün betiği modül yüklenmeden çalışabilir: önceden
// `window.AIProbeSwitcher = {projects: data}` atanmışsa da kullanılır.
const api = (globalThis.AIProbeSwitcher && typeof globalThis.AIProbeSwitcher === 'object') ? globalThis.AIProbeSwitcher : {};
api.VERSION = VERSION;
api.setProjects = (data) => {
  api.projects = data;
  document.querySelectorAll('aiprobe-switcher').forEach((el) => { if (typeof el.setProjects === 'function') el.setProjects(data); });
};
globalThis.AIProbeSwitcher = api;
