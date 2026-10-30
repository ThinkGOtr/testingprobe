import { useEffect, useState } from "react";
import { api, ApiError, type Order } from "../api";
import { Link } from "../components/Link";
import { formatTL } from "../format";
import { routes } from "../router";

export function OrderConfirmationPage({ numara }: { numara: string }) {
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .order(numara)
      .then(setOrder)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Sipariş yüklenemedi."));
  }, [numara]);

  if (error) {
    return (
      <p className="alert alert-error" role="alert">
        {error}
      </p>
    );
  }
  if (!order) return <p className="muted">Sipariş yükleniyor…</p>;

  return (
    <section className="panel confirmation" data-testid="order-confirmation" aria-labelledby="confirm-title">
      <div className="confirm-icon" aria-hidden="true">
        ✓
      </div>
      <h1 id="confirm-title">Siparişiniz alındı</h1>
      <p>
        Sipariş numaranız: <strong data-testid="order-number">{order.numara}</strong>
      </p>
      <dl className="confirm-summary">
        <div>
          <dt>Ürün adedi</dt>
          <dd>{order.adet_toplam}</dd>
        </div>
        <div>
          <dt>Kampanya indirimi</dt>
          <dd data-testid="order-discount">{formatTL(order.indirim)}</dd>
        </div>
        <div>
          <dt>Genel toplam</dt>
          <dd data-testid="order-total">{formatTL(order.toplam)}</dd>
        </div>
      </dl>
      <div className="confirm-actions">
        <Link href={routes.orders} className="btn btn-primary" data-testid="go-orders">
          Siparişlerime git
        </Link>
        <Link href={routes.catalog} className="btn btn-ghost" data-testid="go-catalog">
          Alışverişe devam et
        </Link>
      </div>
    </section>
  );
}
