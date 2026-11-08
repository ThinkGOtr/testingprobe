import { StyleSheet, Text } from "react-native";
import { renk } from "../tema";

interface Props {
  metin: string;
  tur: "hata" | "uyari";
  testID?: string;
}

/** Web'deki `.alert` (role="alert") karşılığı: kimlik metnin kendisindedir, metin tam mesajdır. */
export function Uyari({ metin, tur, testID }: Props) {
  return (
    <Text
      testID={testID}
      accessibilityRole="alert"
      accessibilityLiveRegion="assertive"
      style={[stiller.taban, tur === "hata" ? stiller.hata : stiller.uyari]}
    >
      {metin}
    </Text>
  );
}

const stiller = StyleSheet.create({
  taban: {
    borderRadius: 8,
    borderWidth: 1,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
    marginVertical: 8,
  },
  hata: { backgroundColor: renk.dangerSoft, borderColor: renk.danger, color: renk.danger },
  uyari: { backgroundColor: renk.warningSoft, borderColor: renk.warningBorder, color: renk.warningText },
});
