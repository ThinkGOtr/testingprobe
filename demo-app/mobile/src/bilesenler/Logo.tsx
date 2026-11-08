import { StyleSheet, View } from "react-native";
import { renk } from "../tema";

/** Jenerik içecek dağıtıcısı logosu (marka yok) — web Logo.tsx'in SVG'siz sadeleştirilmiş hali. */
export function Logo({ boyut = 32 }: { boyut?: number }) {
  const o = boyut / 32;
  return (
    <View
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[stiller.kutu, { width: boyut, height: boyut, borderRadius: 8 * o }]}
    >
      <View style={[stiller.sise, { width: 12 * o, height: 20 * o, borderRadius: 3 * o, marginTop: 4 * o }]}>
        <View style={[stiller.etiket, { height: 4 * o, marginTop: 8 * o }]} />
      </View>
    </View>
  );
}

const stiller = StyleSheet.create({
  kutu: { backgroundColor: renk.primary, alignItems: "center", justifyContent: "center" },
  sise: { backgroundColor: "#ffffff" },
  etiket: { backgroundColor: renk.accent },
});
