/*! @aiprobe/switcher — <aiprobe-switcher> ürün değiştirici. Bağımlılık yok, derleme gerekmez.
 *
 * Kullanım:
 *   <script type="module" src="/vendor/switcher-1.0.1.js" integrity="sha384-…"></script>
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
 * 1.0.1: çıkış POST (CSRF) formu; gizli ürünler rol varsa görünür; "Keşfet" satırları soluk değil
 *        (AA kontrast, yalnız logo gri); admin-url; logo adresi home-origin'e göre çözülür.
 * Özellikler:   .me (nesne verilirse me-url çağrılmaz), .refresh()
 * Olaylar:      aiprobe:navigate  {productId, url, kind}  — cancelable; preventDefault gezinmeyi durdurur
 *               aiprobe:lang      {lang}                  — kullanıcı dil değiştirdi (ürün kaydeder)
 *
 * "Başlat" (on_demand ürün kapalı): POST /api/v1/products/{id}/start Firebase ID token ister; ürün
 * sayfalarında bu token yoktur. Bu yüzden değiştirici {home}/?start=<id> adresine bağlanır; başlatmayı
 * home sayfası (kullanıcı onayıyla) yapar.
 */

export const VERSION = '1.0.1';
const DEFAULT_HOME = 'https://home.aiprobe.antreklabs.com';
const STATUS_TTL_MS = 30_000;

const I18N = {
  tr: {
    open: 'AI Probe ürünleri', title: 'AI Probe', yours: 'Ürünleriniz', discover: 'Keşfet',
    request: 'Erişim iste', current: 'Buradasınız', stopped: 'Kapalı · Başlat', starting: 'Başlatılıyor…',
    home: 'Başlangıç', account: 'Hesap', admin: 'Yönetim', language: 'Dil', logout: 'Çıkış', beta: 'beta',
    preview: 'önizleme', deprecated: 'kullanımdan kalkıyor', loadError: 'Ürün listesi yüklenemedi.',
    retry: 'Tekrar dene', loading: 'Yükleniyor…', productMenu: 'Bu ürün', other: 'Diğer ürünler',
  },
  en: {
    open: 'AI Probe products', title: 'AI Probe', yours: 'Your products', discover: 'Discover',
    request: 'Request access', current: 'You are here', stopped: 'Stopped · Start', starting: 'Starting…',
    home: 'Home', account: 'Account', admin: 'Admin', language: 'Language', logout: 'Sign out', beta: 'beta',
    preview: 'preview', deprecated: 'deprecated', loadError: 'Could not load products.',
    retry: 'Retry', loading: 'Loading…', productMenu: 'This product', other: 'Other products',
  },
};

const CSS = `
:host { position: relative; display: inline-block; font-family: var(--aip-font, system-ui, sans-serif);
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

const ICON = '<svg viewBox="0 0 20 20" aria-hidden="true" focusable="false" fill="currentColor">' +
  [3, 10, 17].flatMap((y) => [3, 10, 17].map((x) => `<circle cx="${x}" cy="${y}" r="1.9"/>`)).join('') + '</svg>';

let uid = 0;

export class AiprobeSwitcher extends HTMLElement {
  static get observedAttributes() { return ['lang', 'product', 'home-origin']; }

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
    root.append(this._btn, this._panel);
    this._onDocPointer = (e) => { if (this._open && !e.composedPath().includes(this)) this.close(false); };
    this._onDocKey = (e) => { if (this._open && e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); this.close(); } };
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
  }

  disconnectedCallback() {
    document.removeEventListener('pointerdown', this._onDocPointer, true);
    document.removeEventListener('keydown', this._onDocKey);
  }

  attributeChangedCallback(name, oldV, newV) {
    if (oldV === newV || !this.isConnected) return;
    if (name === 'home-origin') { this._catalog = null; this._status = null; this._load(); }
    this._btn.setAttribute('aria-label', this.t('open'));
    this._btn.title = this.t('open');
    this._render();
  }

  async refresh() { this._catalog = null; this._status = null; this._statusAt = 0; if (!this._meProvided) this._me = undefined; await this._load(); }

  async _load() {
    const jobs = [];
    if (!this._catalog) {
      jobs.push(fetch(`${this.homeOrigin}/sdk/products.json`, { credentials: 'omit' })
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
    this._open = true;
    this._panel.hidden = false;
    this._btn.setAttribute('aria-expanded', 'true');
    if (!this._catalog) this._load();
    this._loadStatus();
    this._render();
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

  /** Erişim: 'yes' | 'no' | 'unknown'. me.products (kod→roller) varsa kesin; yoksa yalnız bu ürün bilinir. */
  _access(p) {
    const me = this._me;
    if (!me) return 'unknown';
    if (me.products && typeof me.products === 'object') return (me.products[p.code] || []).length ? 'yes' : 'no';
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
    const appUrl = safeUrl(p.app_url, home);
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
      h('button', { type: 'button', 'data-lang-toggle': true, 'data-key': 'lang',
        'aria-label': `${t('language')}: ${this.lang.toUpperCase()} → ${other.toUpperCase()}`, onclick: () => this._setLang(other) },
      h('span', { text: t('language') }),
      h('span', { class: 'lang', 'aria-hidden': 'true' },
        h('span', { 'aria-current': String(this.lang === 'tr'), text: 'TR' }),
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
