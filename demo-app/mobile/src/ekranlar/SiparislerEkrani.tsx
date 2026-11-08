import { useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { api, ApiError, type OrderSummary } from "../api";
import { formatDateTime, formatTL } from "../bicim";
import { Dugme } from "../bilesenler/Dugme";
import { Uyari } from "../bilesenler/Uyari";
import type { Ekran } from "../gezinti";
import { tid } from "../kimlik";
import { ortak, renk } from "../tema";

/** Web OrdersPage.tsx karşılığı: onaylanan siparişler, en yenisi üstte. */
export function SiparislerEkrani({ git }: { git: (e: Ekran) => void }) {
  const [orders, setOrders] = useState<OrderSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .orders()
      .then(setOrders)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Siparişler yüklenemedi."));
  }, []);

  return (
    <ScrollView contentContainerStyle={stiller.kaydirma}>
      <View style={ortak.sayfaBasi}>
        <Text style={ortak.h1} accessibilityRole="header">
          Siparişlerim
        </Text>
        <Text style={ortak.muted}>Onaylanan siparişleriniz, en yenisi üstte.</Text>
      </View>
      {error && <Uyari tur="hata" metin={error} />}
      {!orders && !error && <Text style={ortak.muted}>Siparişler yükleniyor…</Text>}
      {orders && orders.length === 0 && (
        <View {...tid("orders-empty")} style={[ortak.panel, ortak.bos]}>
          <Text style={ortak.metin}>Henüz siparişiniz yok.</Text>
          <Dugme metin="Kataloğa git" onPress={() => git({ ad: "katalog" })} />
        </View>
      )}
      {orders && orders.length > 0 && (
        <View {...tid("orders-table")} accessibilityLabel="Sipariş geçmişi" style={stiller.tablo}>
          {orders.map((o) => (
            // Satır dokunulabilir DEĞİL: içindeki kimlikli toplam iOS'ta katlanmasın; bağlantı numaradadır.
            <View key={o.numara} {...tid(`order-row-${o.numara}`)} style={[ortak.panel, stiller.satir]}>
              <View style={stiller.satirUst}>
                <Dugme
                  metin={o.numara}
                  tur="baglanti"
                  accessibilityRole="link"
                  onPress={() => git({ ad: "siparis", numara: o.numara })}
                  style={stiller.numara}
                />
                <Text style={ortak.muted}>{formatDateTime(o.olusturma)}</Text>
              </View>
              <View style={stiller.hucreler}>
                <View style={stiller.hucre}>
                  <Text style={stiller.etiket}>Adet</Text>
                  <Text style={stiller.deger}>{o.adet_toplam}</Text>
                </View>
                <View style={stiller.hucre}>
                  <Text style={stiller.etiket}>İndirim</Text>
                  <Text style={stiller.deger}>{formatTL(o.indirim)}</Text>
                </View>
                <View style={stiller.hucre}>
                  <Text style={stiller.etiket}>Toplam</Text>
                  <Text {...tid(`order-total-${o.numara}`)} style={[stiller.deger, stiller.toplam]}>
                    {formatTL(o.toplam)}
                  </Text>
                </View>
              </View>
            </View>
          ))}
        </View>
      )}
    </ScrollView>
  );
}

const stiller = StyleSheet.create({
  kaydirma: { padding: 16, paddingBottom: 32 },
  tablo: { gap: 12 },
  satir: { gap: 8 },
  satirUst: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  numara: { paddingHorizontal: 0 },
  hucreler: { flexDirection: "row", gap: 8 },
  hucre: { flex: 1, gap: 2 },
  etiket: { fontSize: 12, color: renk.muted },
  deger: { fontSize: 15, color: renk.text },
  toplam: { fontWeight: "700" },
});
