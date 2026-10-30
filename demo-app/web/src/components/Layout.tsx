import type { ReactNode } from "react";
import type { User } from "../api";
import { routes } from "../router";
import { Link } from "./Link";
import { Logo } from "./Logo";

interface Props {
  user: User;
  cartCount: number;
  path: string;
  onLogout: () => void;
  children: ReactNode;
}

export function Layout({ user, cartCount, path, onLogout, children }: Props) {
  const current = (p: string) => (path.startsWith(p) ? "page" : undefined);
  return (
    <div className="shell">
      <a className="skip-link" href="#icerik">
        İçeriğe geç
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <Link href={routes.catalog} className="brand">
            <Logo />
            <span>Bayi Sipariş Portalı</span>
          </Link>
          <nav aria-label="Ana menü" className="mainnav">
            <Link href={routes.catalog} data-testid="nav-catalog" aria-current={current(routes.catalog)}>
              Katalog
            </Link>
            <Link href={routes.cart} data-testid="nav-cart" aria-current={current(routes.cart)}>
              Sepet
              <span className="badge" data-testid="cart-count">
                {cartCount}
              </span>
              <span className="sr-only"> ürün</span>
            </Link>
            <Link
              href={routes.orders}
              data-testid="nav-orders"
              aria-current={path.startsWith(routes.orders) || path.startsWith("/siparis/") ? "page" : undefined}
            >
              Siparişlerim
            </Link>
          </nav>
          <div className="account">
            <span className="account-name" data-testid="current-dealer">
              {user.ad}
            </span>
            <button type="button" className="btn btn-ghost" data-testid="nav-logout" onClick={onLogout}>
              Çıkış yap
            </button>
          </div>
        </div>
      </header>
      <main id="icerik" className="content" tabIndex={-1}>
        {children}
      </main>
      <footer className="footer">Bayi Sipariş Portalı · Örnek uygulama · Tüm veriler sentetiktir</footer>
    </div>
  );
}
