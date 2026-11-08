import { useEffect, useState } from "react";
import { Keyboard, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { api, ApiError, type Cart, type Product } from "../api";
import { formatTL } from "../bicim";
import { Dugme } from "../bilesenler/Dugme";
import { Uyari } from "../bilesenler/Uyari";
import { tid } from "../kimlik";
import { ortak, renk, RADIUS } from "../tema";

interface Props {
  onCartChange: (cart: Cart) => void;
}

const MAX_QTY = 999;

/** Web CatalogPage.tsx karşılığı. Tüm kartlar bağlanır (sanallaştırma yok): kaydırmayla bulunur. */
export function KatalogEkrani({ onCartChange }: Props) {
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
    // iOS sayı klavyesinde "bitti" tuşu yok; açık kalırsa alt sekmeleri (Sepet) örter.
    Keyboard.dismiss();
    const raw = (qty[p.kod] ?? "1").trim();
    const n = raw === "" ? Number.NaN : Number(raw);
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
    <ScrollView
      contentContainerStyle={stiller.kaydirma}
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode="on-drag"
    >
      <View style={ortak.sayfaBasi}>
        <Text style={ortak.h1} accessibilityRole="header">
          Ürün kataloğu
        </Text>
        <Text style={ortak.muted}>Adet seçip ürünleri sepetinize ekleyin. Fiyatlara KDV dahildir.</Text>
      </View>
      {error && <Uyari tur="hata" metin={error} />}
      {!products && !error && <Text style={ortak.muted}>Ürünler yükleniyor…</Text>}
      <View {...tid("product-list")} style={stiller.liste}>
        {products?.map((p) => {
          const bildirim = notice?.kod === p.kod ? notice : null;
          return (
            <View key={p.kod} {...tid(`product-card-${p.kod}`)} style={[ortak.panel, stiller.kart]}>
              <View style={stiller.kartUst}>
                <View style={stiller.gorsel} importantForAccessibility="no-hide-descendants" accessibilityElementsHidden>
                  <Text style={stiller.gorselHarf}>{p.ad.charAt(0)}</Text>
                </View>
                <View style={stiller.kartBilgi}>
                  <Text style={stiller.kod}>{p.kod}</Text>
                  <Text style={stiller.ad} accessibilityRole="header">
                    {p.ad}
                  </Text>
                  {p.kampanya && <Text style={stiller.kampanya}>Kampanya: {p.kampanya}</Text>}
                  <Text {...tid(`product-price-${p.kod}`)} style={stiller.fiyat}>
                    {formatTL(p.fiyat)}
                  </Text>
                </View>
              </View>
              <View style={stiller.eylemler}>
                <View style={stiller.adetAlani}>
                  <Text style={stiller.adetEtiket}>Adet</Text>
                  <TextInput
                    {...tid(`qty-input-${p.kod}`)}
                    accessibilityLabel="Adet"
                    style={stiller.adetGirdi}
                    keyboardType="number-pad"
                    inputMode="numeric"
                    value={qty[p.kod] ?? "1"}
                    onChangeText={(v) => setQty((q) => ({ ...q, [p.kod]: v }))}
                    selectTextOnFocus
                  />
                </View>
                <Dugme
                  {...tid("add-to-cart")}
                  metin="Sepete ekle"
                  onPress={() => add(p)}
                  devreDisi={busy === p.kod}
                  style={stiller.ekle}
                />
              </View>
              <Text
                {...tid(`product-status-${p.kod}`)}
                accessibilityLiveRegion="polite"
                style={[stiller.durum, bildirim && (bildirim.ok ? stiller.durumOk : stiller.durumHata)]}
              >
                {bildirim ? bildirim.text : ""}
              </Text>
            </View>
          );
        })}
      </View>
    </ScrollView>
  );
}

const stiller = StyleSheet.create({
  kaydirma: { padding: 16, paddingBottom: 32 },
  liste: { gap: 12 },
  kart: { gap: 12 },
  kartUst: { flexDirection: "row", gap: 12 },
  gorsel: {
    width: 56,
    height: 56,
    borderRadius: RADIUS,
    backgroundColor: renk.primarySoft,
    alignItems: "center",
    justifyContent: "center",
  },
  gorselHarf: { fontSize: 24, fontWeight: "700", color: renk.primary },
  kartBilgi: { flex: 1, gap: 2 },
  kod: { fontSize: 12, color: renk.muted },
  ad: { fontSize: 16, fontWeight: "700", color: renk.text },
  kampanya: {
    alignSelf: "flex-start",
    backgroundColor: renk.accentSoft,
    color: renk.accentText,
    fontSize: 12,
    fontWeight: "600",
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 6,
    overflow: "hidden",
    marginTop: 2,
  },
  fiyat: { fontSize: 18, fontWeight: "700", color: renk.text, marginTop: 4 },
  eylemler: { flexDirection: "row", alignItems: "flex-end", gap: 12 },
  adetAlani: { gap: 4 },
  adetEtiket: { fontSize: 13, fontWeight: "600", color: renk.text },
  adetGirdi: {
    width: 80,
    minHeight: 44,
    borderWidth: 1,
    borderColor: renk.border,
    borderRadius: 8,
    paddingHorizontal: 10,
    fontSize: 16,
    color: renk.text,
    backgroundColor: renk.surface,
  },
  ekle: { flex: 1 },
  // Boşken de yer kaplar: kimlikli eleman ağaçta her zaman bulunur (web'de de boş <p> durur).
  durum: { minHeight: 20, fontSize: 14, color: renk.muted },
  durumOk: { color: renk.success },
  durumHata: { color: renk.danger },
});
