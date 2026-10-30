import { useEffect, useState } from "react";
import { api, ApiError, type OrderSummary } from "../api";
import { Link } from "../components/Link";
import { formatDateTime, formatTL } from "../format";
import { routes } from "../router";

export function OrdersPage() {
  const [orders, setOrders] = useState<OrderSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .orders()
      .then(setOrders)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Siparişler yüklenemedi."));
  }, []);

  return (
    <>
      <div className="page-head">
        <h1>Siparişlerim</h1>
        <p className="muted">Onaylanan siparişleriniz, en yenisi üstte.</p>
      </div>
      {error && (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      )}
      {!orders && !error && <p className="muted">Siparişler yükleniyor…</p>}
      {orders && orders.length === 0 && (
        <div className="empty" data-testid="orders-empty">
          <p>Henüz siparişiniz yok.</p>
          <Link href={routes.catalog} className="btn btn-primary">
            Kataloğa git
          </Link>
        </div>
      )}
      {orders && orders.length > 0 && (
        <div className="panel table-wrap">
          <table className="table" data-testid="orders-table">
            <caption className="sr-only">Sipariş geçmişi</caption>
            <thead>
              <tr>
                <th scope="col">Sipariş no</th>
                <th scope="col">Tarih</th>
                <th scope="col" className="num">
                  Adet
                </th>
                <th scope="col" className="num">
                  İndirim
                </th>
                <th scope="col" className="num">
                  Toplam
                </th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.numara} data-testid={`order-row-${o.numara}`}>
                  <th scope="row">
                    <Link href={routes.order(o.numara)}>{o.numara}</Link>
                  </th>
                  <td>{formatDateTime(o.olusturma)}</td>
                  <td className="num">{o.adet_toplam}</td>
                  <td className="num">{formatTL(o.indirim)}</td>
                  <td className="num" data-testid={`order-total-${o.numara}`}>
                    {formatTL(o.toplam)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
