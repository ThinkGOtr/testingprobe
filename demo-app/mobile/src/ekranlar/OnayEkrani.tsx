import { useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { api, ApiError, type Order } from "../api";
import { formatTL } from "../bicim";
import { Dugme } from "../bilesenler/Dugme";
import { Uyari } from "../bilesenler/Uyari";
import type { Ekran } from "../gezinti";
import { tid } from "../kimlik";
import { ortak, renk } from "../tema";

/** Web OrderConfirmationPage.tsx karşılığı. */
export function OnayEkrani({ numara, git }: { numara: string; git: (e: Ekran) => void }) {
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .order(numara)
      .then(setOrder)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Sipariş yüklenemedi."));
  }, [numara]);

  return (
    <ScrollView contentContainerStyle={stiller.kaydirma}>
      {error && <Uyari tur="hata" metin={error} />}
      {!order && !error && <Text style={ortak.muted}>Sipariş yükleniyor…</Text>}
      {order && (
        <View
          {...tid("order-confirmation")}
          accessibilityLabel="Siparişiniz alındı"
          style={[ortak.panel, stiller.onay]}
        >
          <View style={stiller.ikon} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
            <Text style={stiller.ikonMetin}>✓</Text>
          </View>
          <Text style={ortak.h1} accessibilityRole="header">
            Siparişiniz alındı
          </Text>
          {/* Numara ayrı <Text>: iç içe Text kendi görünümünü oluşturmaz, kimliği kaybolurdu. */}
          <View style={stiller.numaraSatir}>
            <Text style={ortak.metin}>Sipariş numaranız:</Text>
            <Text {...tid("order-number")} style={stiller.numara}>
              {order.numara}
            </Text>
          </View>
          <View style={stiller.ozet}>
            <View style={stiller.ozetSatir}>
              <Text style={stiller.ozetEtiket}>Ürün adedi</Text>
              <Text style={stiller.ozetDeger}>{order.adet_toplam}</Text>
            </View>
            <View style={stiller.ozetSatir}>
              <Text style={stiller.ozetEtiket}>Kampanya indirimi</Text>
              <Text {...tid("order-discount")} style={stiller.ozetDeger}>
                {formatTL(order.indirim)}
              </Text>
            </View>
            <View style={stiller.ozetSatir}>
              <Text style={stiller.ozetEtiket}>Genel toplam</Text>
              <Text {...tid("order-total")} style={[stiller.ozetDeger, stiller.toplam]}>
                {formatTL(order.toplam)}
              </Text>
            </View>
          </View>
          <View style={stiller.eylemler}>
            <Dugme
              {...tid("go-orders")}
              metin="Siparişlerime git"
              accessibilityRole="link"
              onPress={() => git({ ad: "siparisler" })}
              blok
            />
            <Dugme
              {...tid("go-catalog")}
              metin="Alışverişe devam et"
              tur="hayalet"
              accessibilityRole="link"
              onPress={() => git({ ad: "katalog" })}
              blok
            />
          </View>
        </View>
      )}
    </ScrollView>
  );
}

const stiller = StyleSheet.create({
  kaydirma: { padding: 16, paddingBottom: 32 },
  onay: { alignItems: "center", gap: 12, paddingVertical: 24 },
  ikon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: renk.successSoft,
    alignItems: "center",
    justifyContent: "center",
  },
  ikonMetin: { fontSize: 28, color: renk.success, fontWeight: "700" },
  numaraSatir: { flexDirection: "row", gap: 6, alignItems: "baseline", flexWrap: "wrap", justifyContent: "center" },
  numara: { fontSize: 16, fontWeight: "700", color: renk.text },
  ozet: { alignSelf: "stretch", gap: 8, marginTop: 4 },
  ozetSatir: { flexDirection: "row", justifyContent: "space-between", gap: 8 },
  ozetEtiket: { fontSize: 15, color: renk.muted },
  ozetDeger: { fontSize: 15, color: renk.text },
  toplam: { fontWeight: "700" },
  eylemler: { alignSelf: "stretch", gap: 8, marginTop: 8 },
});
