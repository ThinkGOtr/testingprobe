import { Pressable, StyleSheet, Text, type StyleProp, type ViewStyle } from "react-native";
import { renk } from "../tema";

interface Props {
  /** Görünen metin; erişilebilirlik adı da budur (accessibilityLabel verilmezse). */
  metin: string;
  onPress: () => void;
  tur?: "birincil" | "hayalet" | "baglanti";
  devreDisi?: boolean;
  /** Kimlik: `{...tid("…")}` ile verilir; yoksa düğme kimliksizdir. */
  testID?: string;
  accessibilityLabel?: string;
  accessibilityRole?: "button" | "link";
  secili?: boolean;
  blok?: boolean;
  style?: StyleProp<ViewStyle>;
}

/**
 * Dokunulabilir düğme. Pressable erişilebilir tek elemandır: içindeki <Text> ayrı eleman olarak
 * görünmez; bu yüzden düğmenin İÇİNE kimlikli başka eleman konmaz (bkz. kimlik.ts).
 */
export function Dugme({
  metin,
  onPress,
  tur = "birincil",
  devreDisi = false,
  testID,
  accessibilityLabel,
  accessibilityRole = "button",
  secili,
  blok = false,
  style,
}: Props) {
  return (
    <Pressable
      testID={testID}
      accessibilityRole={accessibilityRole}
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ disabled: devreDisi, selected: secili }}
      disabled={devreDisi}
      onPress={onPress}
      hitSlop={4}
      style={({ pressed }) => [
        stiller.taban,
        tur === "birincil" && stiller.birincil,
        tur === "hayalet" && stiller.hayalet,
        tur === "baglanti" && stiller.baglanti,
        blok && stiller.blok,
        devreDisi && stiller.devreDisi,
        pressed && !devreDisi && stiller.basili,
        style,
      ]}
    >
      <Text
        style={[
          stiller.metin,
          tur === "birincil" && stiller.birincilMetin,
          tur !== "birincil" && stiller.ikincilMetin,
        ]}
      >
        {metin}
      </Text>
    </Pressable>
  );
}

const stiller = StyleSheet.create({
  taban: {
    minHeight: 44,
    paddingHorizontal: 16,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
  },
  birincil: { backgroundColor: renk.primary },
  hayalet: { backgroundColor: renk.surface, borderWidth: 1, borderColor: renk.border },
  baglanti: { paddingHorizontal: 8, minHeight: 36 },
  blok: { alignSelf: "stretch" },
  devreDisi: { opacity: 0.5 },
  basili: { opacity: 0.8 },
  metin: { fontSize: 15, fontWeight: "600" },
  birincilMetin: { color: "#ffffff" },
  ikincilMetin: { color: renk.primary },
});
