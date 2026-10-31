import { useCallback, useEffect, useState } from "react";
import { api, setUnauthorizedHandler, type Cart, type User } from "./api";
import { Layout } from "./components/Layout";
import { Link } from "./components/Link";
import { CartPage } from "./pages/CartPage";
import { CatalogPage } from "./pages/CatalogPage";
import { LoginPage } from "./pages/LoginPage";
import { OrderConfirmationPage } from "./pages/OrderConfirmationPage";
import { OrdersPage } from "./pages/OrdersPage";
import { navigate, routes, usePath } from "./router";

// Kural: her etkileşimli elemanda data-testid bulunur (locator'lar e2e/pages/**/locators.ts içinde).
export function App() {
  const path = usePath();
  // undefined: oturum kontrol ediliyor · null: giriş yapılmamış
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [cart, setCart] = useState<Cart | null>(null);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null);
      setCart(null);
    });
    api
      .session()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  useEffect(() => {
    if (user) api.cart().then(setCart).catch(() => setCart(null));
  }, [user]);

  // Yönlendirme kuralları: oturumsuz → giriş; oturumlu → giriş sayfası yerine katalog.
  useEffect(() => {
    if (user === undefined) return;
    if (user === null && path !== routes.login) navigate(routes.login, true);
    else if (user && (path === routes.login || path === "/")) navigate(routes.catalog, true);
  }, [user, path]);

  useEffect(() => {
    const titles: Record<string, string> = {
      [routes.login]: "Giriş",
      [routes.catalog]: "Katalog",
      [routes.cart]: "Sepet",
      [routes.orders]: "Siparişlerim",
    };
    const t = titles[path] ?? (path.startsWith("/siparis/") ? "Sipariş onayı" : null);
    document.title = t ? `${t} · Bayi Sipariş Portalı` : "Bayi Sipariş Portalı";
  }, [path]);

  const onCartChange = useCallback((c: Cart) => setCart(c), []);

  async function logout() {
    try {
      await api.logout();
    } finally {
      setUser(null);
      setCart(null);
    }
  }

  if (user === undefined) {
    return (
      <p className="boot muted" role="status">
        Yükleniyor…
      </p>
    );
  }
  if (user === null) return <LoginPage onLoggedIn={setUser} />;

  let page;
  if (path === routes.catalog) page = <CatalogPage onCartChange={onCartChange} />;
  else if (path === routes.cart) page = <CartPage cart={cart} onCartChange={onCartChange} />;
  else if (path === routes.orders) page = <OrdersPage />;
  else if (path.startsWith("/siparis/")) {
    const numara = decodeURIComponent(path.slice("/siparis/".length));
    page = <OrderConfirmationPage key={numara} numara={numara} />;
  } else if (path === "/" || path === routes.login) page = null;
  else
    page = (
      <div className="empty">
        <h1>Sayfa bulunamadı</h1>
        <Link href={routes.catalog} className="btn btn-primary">
          Kataloğa dön
        </Link>
      </div>
    );

  return (
    <Layout user={user} cartCount={cart?.adet_toplam ?? 0} path={path} onLogout={logout}>
      {page}
    </Layout>
  );
}
