import { useEffect, useState, type ReactNode } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { api, ApiError, type Cart, type CartLine } from "../api";
import { formatTL } from "../bicim";
import { Dugme } from "../bilesenler/Dugme";
import { Uyari } from "../bilesenler/Uyari";
import type { Ekran } from "../gezinti";
import { tid } from "../kimlik";
import { ortak, renk } from "../tema";

interface Props {
  cart: Cart | null;
  onCartChange: (cart: Cart) => void;
  git: (e: Ekran) => void;
}

/** Web CartPage.tsx karşılığı: aynı satırlar, aynı özet, aynı uyarılar, aynı onay kuralı. */
export function SepetEkrani({ cart, onCartChange, git }: Props) {
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
      git({ ad: "siparis", numara: order.numara });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sipariş onaylanamadı.");
      setBusy(false);
    }
  }

  const baslik = (
    <View style={ortak.sayfaBasi}>
      <Text style={ortak.h1} accessibilityRole="header">
        Sepetim
      </Text>
      {cart && <Text style={ortak.muted}>Kampanya indirimleri sepet toplamına otomatik uygulanır.</Text>}
    </View>
  );

  if (!cart) {
    return (
      <ScrollView contentContainerStyle={stiller.kaydirma}>
        {baslik}
        {error ? <Uyari tur="hata" metin={error} /> : <Text style={ortak.muted}>Sepet yükleniyor…</Text>}
      </ScrollView>
    );
  }

  const empty = cart.satirlar.length === 0;
  const minWarning = cart.uyarilar.find((w) => w.kod === "min_siparis");
  const hasDiscount = Number(cart.indirim) > 0;

  return (
    <ScrollView contentContainerStyle={stiller.kaydirma}>
      {baslik}
      {empty ? (
        <View {...tid("cart-empty")} style={[ortak.panel, ortak.bos]}>
          <Text style={ortak.metin}>Sepetiniz boş.</Text>
          <Dugme metin="Kataloğa dön" onPress={() => git({ ad: "katalog" })} />
        </View>
      ) : (
        <View style={stiller.duzen}>
          <View {...tid("cart-table")} accessibilityLabel="Sepetteki ürünler" style={stiller.tablo}>
            {cart.satirlar.map((l) => (
              <SepetSatiri key={l.urun_kod} satir={l} onRemove={() => remove(l.urun_kod)} />
            ))}
          </View>
          <View style={[ortak.panel, stiller.ozet]}>
            <Text style={ortak.h2} accessibilityRole="header">
              Sipariş özeti
            </Text>
            <View style={stiller.ozetSatir}>
              <Text style={stiller.ozetEtiket}>Ara toplam</Text>
              <Text {...tid("cart-subtotal")} style={stiller.ozetDeger}>
                {formatTL(cart.ara_toplam)}
              </Text>
            </View>
            <View style={stiller.ozetSatir}>
              <Text style={stiller.ozetEtiket}>Kampanya indirimi</Text>
              <View style={stiller.indirimKutu}>
                {hasDiscount && (
                  <Text style={[stiller.ozetDeger, stiller.indirim]} accessibilityElementsHidden importantForAccessibility="no">
                    −
                  </Text>
                )}
                <Text {...tid("cart-discount")} style={[stiller.ozetDeger, hasDiscount && stiller.indirim]}>
                  {formatTL(cart.indirim)}
                </Text>
              </View>
            </View>
            <View style={[stiller.ozetSatir, stiller.toplamSatir]}>
              <Text style={stiller.toplamEtiket}>Genel toplam</Text>
              <Text {...tid("cart-total")} style={stiller.toplamDeger}>
                {formatTL(cart.toplam)}
              </Text>
            </View>
            {minWarning && <Uyari {...tid("min-order-warning")} tur="uyari" metin={minWarning.mesaj} />}
            {error && <Uyari {...tid("checkout-error")} tur="hata" metin={error} />}
            <Dugme
              {...tid("checkout-submit")}
              metin={busy ? "Onaylanıyor…" : "Siparişi onayla"}
              onPress={checkout}
              devreDisi={!cart.onaylanabilir || busy}
              blok
            />
          </View>
        </View>
      )}
      {empty && error && <Uyari tur="hata" metin={error} />}
    </ScrollView>
  );
}

function SepetSatiri({ satir: l, onRemove }: { satir: CartLine; onRemove: () => void }) {
  return (
    <View {...tid(`cart-line-${l.urun_kod}`)} style={[ortak.panel, stiller.satir]}>
      <View style={stiller.satirUst}>
        <View style={stiller.satirAd}>
          <Text style={stiller.urunAd}>{l.urun_ad}</Text>
          <View style={stiller.meta}>
            <Text style={ortak.muted}>{l.urun_kod}</Text>
            {l.kampanya && <Text style={stiller.kampanya}>{l.kampanya}</Text>}
          </View>
        </View>
        <Dugme
          {...tid(`cart-line-remove-${l.urun_kod}`)}
          metin="Kaldır"
          tur="baglanti"
          accessibilityLabel={`${l.urun_ad} ürününü sepetten kaldır`}
          onPress={onRemove}
        />
      </View>
      <View style={stiller.hucreler}>
        <Hucre etiket="Birim fiyat">
          <Text style={stiller.hucreDeger}>{formatTL(l.birim_fiyat)}</Text>
        </Hucre>
        <Hucre etiket="Adet">
          <Text {...tid(`cart-line-qty-${l.urun_kod}`)} style={stiller.hucreDeger}>
            {l.adet}
          </Text>
        </Hucre>
        <Hucre etiket="Bedava">
          <Text {...tid(`cart-line-free-${l.urun_kod}`)} style={stiller.hucreDeger}>
            {l.bedava_adet}
          </Text>
        </Hucre>
        <Hucre etiket="Tutar">
          <Text {...tid(`cart-line-total-${l.urun_kod}`)} style={[stiller.hucreDeger, stiller.tutar]}>
            {formatTL(l.satir_tutari)}
          </Text>
        </Hucre>
      </View>
    </View>
  );
}

function Hucre({ etiket, children }: { etiket: string; children: ReactNode }) {
  return (
    <View style={stiller.hucre}>
      <Text style={stiller.hucreEtiket}>{etiket}</Text>
      {children}
    </View>
  );
}

const stiller = StyleSheet.create({
  kaydirma: { padding: 16, paddingBottom: 32 },
  duzen: { gap: 16 },
  tablo: { gap: 12 },
  satir: { gap: 12 },
  satirUst: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 8 },
  satirAd: { flex: 1, gap: 2 },
  urunAd: { fontSize: 16, fontWeight: "700", color: renk.text },
  meta: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  kampanya: {
    backgroundColor: renk.accentSoft,
    color: renk.accentText,
    fontSize: 12,
    fontWeight: "600",
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 6,
    overflow: "hidden",
  },
  hucreler: { flexDirection: "row", flexWrap: "wrap", rowGap: 8 },
  hucre: { width: "50%", gap: 2 },
  hucreEtiket: { fontSize: 12, color: renk.muted },
  hucreDeger: { fontSize: 15, color: renk.text },
  tutar: { fontWeight: "700" },
  ozet: { gap: 10 },
  ozetSatir: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 },
  ozetEtiket: { fontSize: 15, color: renk.muted },
  ozetDeger: { fontSize: 15, color: renk.text },
  indirimKutu: { flexDirection: "row", gap: 2 },
  indirim: { color: renk.success },
  toplamSatir: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: renk.border, paddingTop: 10 },
  toplamEtiket: { fontSize: 16, fontWeight: "700", color: renk.text },
  toplamDeger: { fontSize: 18, fontWeight: "700", color: renk.text },
});
