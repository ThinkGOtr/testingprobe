import { useEffect, useState } from "react";
import { api, ApiError, type Cart, type Product } from "../api";
import { formatTL } from "../format";

interface Props {
  onCartChange: (cart: Cart) => void;
}

const MAX_QTY = 999;

export function CatalogPage({ onCartChange }: Props) {
  const [products, setProducts] = useState<Product[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [qty, setQty] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kod: string; text: string; ok: boolean } | null>(null);

  useEffect(() => {
    api
      .products()
      .then(setProducts)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Ürünler yüklenemedi."));
  }, []);

  async function add(p: Product) {
    const raw = qty[p.kod] ?? "1";
    const n = Number(raw);
    if (!Number.isInteger(n) || n < 1 || n > MAX_QTY) {
      setNotice({ kod: p.kod, text: `Adet 1 ile ${MAX_QTY} arasında olmalıdır.`, ok: false });
      return;
    }
    setBusy(p.kod);
    setNotice(null);
    try {
      const cart = await api.addToCart(p.kod, n);
      onCartChange(cart);
      setNotice({ kod: p.kod, text: `${n} adet sepete eklendi.`, ok: true });
    } catch (err) {
      setNotice({ kod: p.kod, text: err instanceof ApiError ? err.message : "Sepete eklenemedi.", ok: false });
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>Ürün kataloğu</h1>
        <p className="muted">Adet seçip ürünleri sepetinize ekleyin. Fiyatlara KDV dahildir.</p>
      </div>
      {error && (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      )}
      {!products && !error && <p className="muted">Ürünler yükleniyor…</p>}
      <div className="product-grid" data-testid="product-list">
        {products?.map((p) => (
          <article
            key={p.kod}
            className="product-card"
            data-testid={`product-card-${p.kod}`}
            aria-labelledby={`product-title-${p.kod}`}
          >
            <div className="product-visual" aria-hidden="true">
              <span>{p.ad.charAt(0)}</span>
            </div>
            <div className="product-body">
              <p className="product-code">{p.kod}</p>
              <h2 id={`product-title-${p.kod}`} className="product-title">
                {p.ad}
              </h2>
              {p.kampanya && <p className="campaign-badge">Kampanya: {p.kampanya}</p>}
              <p className="product-price" data-testid={`product-price-${p.kod}`}>
                {formatTL(p.fiyat)}
              </p>
              <div className="product-actions">
                <div className="qty-field">
                  <label htmlFor={`qty-${p.kod}`}>Adet</label>
                  <input
                    id={`qty-${p.kod}`}
                    data-testid={`qty-input-${p.kod}`}
                    type="number"
                    inputMode="numeric"
                    min={1}
                    max={MAX_QTY}
                    step={1}
                    value={qty[p.kod] ?? "1"}
                    onChange={(e) => setQty((q) => ({ ...q, [p.kod]: e.target.value }))}
                  />
                </div>
                <button
                  type="button"
                  className="btn btn-primary"
                  data-testid="add-to-cart"
                  onClick={() => add(p)}
                  disabled={busy === p.kod}
                >
                  Sepete ekle
                </button>
              </div>
              <p
                className={`card-notice ${notice?.kod === p.kod ? (notice.ok ? "ok" : "err") : ""}`}
                role="status"
                data-testid={`product-status-${p.kod}`}
              >
                {notice?.kod === p.kod ? notice.text : ""}
              </p>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}
