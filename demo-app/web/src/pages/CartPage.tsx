import { useEffect, useState } from "react";
import { api, ApiError, type Cart } from "../api";
import { Link } from "../components/Link";
import { formatTL } from "../format";
import { navigate, routes } from "../router";

interface Props {
  cart: Cart | null;
  onCartChange: (cart: Cart) => void;
}

export function CartPage({ cart, onCartChange }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .cart()
      .then(onCartChange)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Sepet yüklenemedi."));
  }, [onCartChange]);

  async function remove(kod: string) {
    setError(null);
    try {
      onCartChange(await api.removeLine(kod));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ürün kaldırılamadı.");
    }
  }

  async function checkout() {
    setError(null);
    setBusy(true);
    try {
      const order = await api.checkout();
      onCartChange(await api.cart());
      navigate(routes.order(order.numara));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sipariş onaylanamadı.");
      setBusy(false);
    }
  }

  if (!cart) {
    return (
      <>
        <div className="page-head">
          <h1>Sepetim</h1>
        </div>
        {error ? (
          <p className="alert alert-error" role="alert">
            {error}
          </p>
        ) : (
          <p className="muted">Sepet yükleniyor…</p>
        )}
      </>
    );
  }

  const empty = cart.satirlar.length === 0;
  const minWarning = cart.uyarilar.find((w) => w.kod === "min_siparis");
  const hasDiscount = Number(cart.indirim) > 0;

  return (
    <>
      <div className="page-head">
        <h1>Sepetim</h1>
        <p className="muted">Kampanya indirimleri sepet toplamına otomatik uygulanır.</p>
      </div>
      {empty ? (
        <div className="empty" data-testid="cart-empty">
          <p>Sepetiniz boş.</p>
          <Link href={routes.catalog} className="btn btn-primary">
            Kataloğa dön
          </Link>
        </div>
      ) : (
        <div className="cart-layout">
          <div className="panel table-wrap">
            <table className="table table-stack" data-testid="cart-table">
              <caption className="sr-only">Sepetteki ürünler</caption>
              <thead>
                <tr>
                  <th scope="col">Ürün</th>
                  <th scope="col" className="num">
                    Birim fiyat
                  </th>
                  <th scope="col" className="num">
                    Adet
                  </th>
                  <th scope="col" className="num">
                    Bedava
                  </th>
                  <th scope="col" className="num">
                    Tutar
                  </th>
                  <th scope="col">
                    <span className="sr-only">İşlem</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {cart.satirlar.map((l) => (
                  <tr key={l.urun_kod} data-testid={`cart-line-${l.urun_kod}`}>
                    <th scope="row">
                      <span className="line-name">{l.urun_ad}</span>
                      <span className="line-meta">
                        {l.urun_kod}
                        {l.kampanya && <span className="campaign-badge small">{l.kampanya}</span>}
                      </span>
                    </th>
                    <td className="num" data-label="Birim fiyat">
                      {formatTL(l.birim_fiyat)}
                    </td>
                    <td className="num" data-label="Adet">
                      <span data-testid={`cart-line-qty-${l.urun_kod}`}>{l.adet}</span>
                    </td>
                    <td className="num" data-label="Bedava">
                      <span data-testid={`cart-line-free-${l.urun_kod}`}>{l.bedava_adet}</span>
                    </td>
                    <td className="num" data-label="Tutar" data-testid={`cart-line-total-${l.urun_kod}`}>
                      {formatTL(l.satir_tutari)}
                    </td>
                    <td className="actions">
                      <button
                        type="button"
                        className="btn btn-link"
                        data-testid={`cart-line-remove-${l.urun_kod}`}
                        aria-label={`${l.urun_ad} ürününü sepetten kaldır`}
                        onClick={() => remove(l.urun_kod)}
                      >
                        Kaldır
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <aside className="panel summary" aria-labelledby="summary-title">
            <h2 id="summary-title">Sipariş özeti</h2>
            <dl>
              <div>
                <dt>Ara toplam</dt>
                <dd data-testid="cart-subtotal">{formatTL(cart.ara_toplam)}</dd>
              </div>
              <div>
                <dt>Kampanya indirimi</dt>
                <dd className={hasDiscount ? "discount" : undefined}>
                  {hasDiscount && <span aria-hidden="true">−</span>}
                  <span data-testid="cart-discount">{formatTL(cart.indirim)}</span>
                </dd>
              </div>
              <div className="total">
                <dt>Genel toplam</dt>
                <dd data-testid="cart-total">{formatTL(cart.toplam)}</dd>
              </div>
            </dl>
            {minWarning && (
              <p className="alert alert-warning" role="alert" data-testid="min-order-warning">
                {minWarning.mesaj}
              </p>
            )}
            {error && (
              <p className="alert alert-error" role="alert" data-testid="checkout-error">
                {error}
              </p>
            )}
            <button
              type="button"
              className="btn btn-primary btn-block"
              data-testid="checkout-submit"
              disabled={!cart.onaylanabilir || busy}
              onClick={checkout}
            >
              {busy ? "Onaylanıyor…" : "Siparişi onayla"}
            </button>
          </aside>
        </div>
      )}
      {empty && error && (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
