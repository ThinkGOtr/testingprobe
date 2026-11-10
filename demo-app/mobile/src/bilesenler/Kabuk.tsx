import type { ReactNode } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import type { User } from "../api";
import { tid } from "../kimlik";
import type { Ekran } from "../gezinti";
import { renk } from "../tema";
import { Dugme } from "./Dugme";
import { Logo } from "./Logo";

interface Props {
  user: User;
  cartCount: number;
  ekran: Ekran;
  git: (e: Ekran) => void;
  onLogout: () => void;
  children: ReactNode;
}

/**
 * Oturumlu kabuk — web Layout.tsx karşılığı. Üst çubuk: marka, bayi adı (`current-dealer`),
 * çıkış (`nav-logout`). Alt sekme çubuğu: `nav-catalog`, `nav-cart` (+ `cart-count`), `nav-orders`.
 */
export function Kabuk({ user, cartCount, ekran, git, onLogout, children }: Props) {
  const kenar = useSafeAreaInsets();
  const siparisSekmesi = ekran.ad === "siparisler" || ekran.ad === "siparis";
  return (
    <View style={stiller.kok}>
      <View style={[stiller.ust, { paddingTop: kenar.top + 8 }]}>
        <View style={stiller.marka} accessibilityRole="header">
          <Logo boyut={28} />
          <Text style={stiller.markaMetin} numberOfLines={1}>
            Bayi Sipariş Portalı
          </Text>
        </View>
        <View style={stiller.hesap}>
          <Text {...tid("current-dealer")} style={stiller.bayi} numberOfLines={1}>
            {user.ad}
          </Text>
          <Dugme {...tid("nav-logout")} metin="Çıkış yap" tur="hayalet" onPress={onLogout} />
        </View>
      </View>

      <View style={stiller.icerik}>{children}</View>

      <View
        accessibilityRole="tablist"
        accessibilityLabel="Ana menü"
        style={[stiller.sekmeler, { paddingBottom: Math.max(kenar.bottom, 8) }]}
      >
        <Sekme
          {...tid("nav-catalog")}
          metin="Katalog"
          secili={ekran.ad === "katalog"}
          onPress={() => git({ ad: "katalog" })}
        />
        {/* Sayaç düğmenin KARDEŞİDİR: iOS'ta düğmenin çocukları XCUITest'te ayrı eleman olmaz. */}
        <View style={stiller.sekmeKutu}>
          <Sekme
            {...tid("nav-cart")}
            metin="Sepet"
            erisimEtiketi={`Sepet, ${cartCount} ürün`}
            secili={ekran.ad === "sepet"}
            onPress={() => git({ ad: "sepet" })}
          />
          <View pointerEvents="none" style={stiller.rozetYeri}>
            <Text {...tid("cart-count")} style={stiller.rozet}>
              {cartCount}
            </Text>
          </View>
        </View>
        <Sekme
          {...tid("nav-orders")}
          metin="Siparişlerim"
          secili={siparisSekmesi}
          onPress={() => git({ ad: "siparisler" })}
        />
      </View>
    </View>
  );
}

interface SekmeProps {
  testID: string;
  metin: string;
  erisimEtiketi?: string;
  secili: boolean;
  onPress: () => void;
}

function Sekme({ testID, metin, erisimEtiketi, secili, onPress }: SekmeProps) {
  return (
    <Pressable
      testID={testID}
      accessibilityRole="tab"
      accessibilityLabel={erisimEtiketi}
      accessibilityState={{ selected: secili }}
      onPress={onPress}
      style={({ pressed }) => [stiller.sekme, secili && stiller.sekmeSecili, pressed && { opacity: 0.7 }]}
    >
      <Text style={[stiller.sekmeMetin, secili && stiller.sekmeMetinSecili]}>{metin}</Text>
    </Pressable>
  );
}

const stiller = StyleSheet.create({
  kok: { flex: 1, backgroundColor: renk.bg },
  ust: {
    backgroundColor: renk.surface,
    borderBottomColor: renk.border,
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 16,
    paddingBottom: 8,
    gap: 8,
  },
  marka: { flexDirection: "row", alignItems: "center", gap: 8 },
  markaMetin: { fontSize: 16, fontWeight: "700", color: renk.text, flexShrink: 1 },
  hesap: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  bayi: { fontSize: 14, color: renk.muted, flexShrink: 1 },
  icerik: { flex: 1 },
  sekmeler: {
    flexDirection: "row",
    backgroundColor: renk.surface,
    borderTopColor: renk.border,
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingTop: 6,
    paddingHorizontal: 8,
  },
  sekmeKutu: { flex: 1 },
  sekme: {
    flex: 1,
    minHeight: 48,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    marginHorizontal: 4,
  },
  sekmeSecili: { backgroundColor: renk.primarySoft },
  sekmeMetin: { fontSize: 14, fontWeight: "600", color: renk.muted },
  sekmeMetinSecili: { color: renk.primary },
  rozetYeri: { position: "absolute", top: 2, right: 12 },
  rozet: {
    minWidth: 22,
    paddingHorizontal: 6,
    borderRadius: 11,
    overflow: "hidden",
    backgroundColor: renk.accent,
    color: "#ffffff",
    fontSize: 12,
    fontWeight: "700",
    textAlign: "center",
    lineHeight: 20,
  },
});
