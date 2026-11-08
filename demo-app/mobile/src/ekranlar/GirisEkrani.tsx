import { useRef, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputInstance,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api, ApiError, type User } from "../api";
import { Dugme } from "../bilesenler/Dugme";
import { Logo } from "../bilesenler/Logo";
import { Uyari } from "../bilesenler/Uyari";
import { tid } from "../kimlik";
import { ortak, renk, RADIUS } from "../tema";

interface Props {
  onLoggedIn: (user: User) => void;
}

/** Web LoginPage.tsx karşılığı. */
export function GirisEkrani({ onLoggedIn }: Props) {
  const kenar = useSafeAreaInsets();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const parolaRef = useRef<TextInputInstance>(null);

  const gonderilebilir = !busy && !!username && !!password;

  async function submit() {
    if (!gonderilebilir) return;
    setError(null);
    setBusy(true);
    try {
      onLoggedIn(await api.login(username.trim(), password));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Giriş yapılamadı.");
      setBusy(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={stiller.kok}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView
        contentContainerStyle={[stiller.kaydirma, { paddingTop: kenar.top + 32 }]}
        keyboardShouldPersistTaps="handled"
      >
        <View style={[ortak.panel, stiller.kart]}>
          <View style={stiller.marka}>
            <Logo />
            <Text style={stiller.markaMetin}>Bayi Sipariş Portalı</Text>
          </View>
          <Text style={ortak.h1} accessibilityRole="header">
            Bayi girişi
          </Text>
          <Text style={ortak.muted}>Sipariş vermek için bayi hesabınızla giriş yapın.</Text>

          <View style={stiller.alan}>
            <Text style={stiller.etiket} nativeID="giris-kullanici-etiket">
              Kullanıcı adı
            </Text>
            <TextInput
              {...tid("login-username")}
              accessibilityLabel="Kullanıcı adı"
              accessibilityLabelledBy="giris-kullanici-etiket"
              style={stiller.girdi}
              value={username}
              onChangeText={setUsername}
              autoCapitalize="none"
              autoCorrect={false}
              autoComplete="username"
              textContentType="username"
              returnKeyType="next"
              onSubmitEditing={() => parolaRef.current?.focus()}
              submitBehavior="submit"
            />
          </View>
          <View style={stiller.alan}>
            <Text style={stiller.etiket} nativeID="giris-parola-etiket">
              Parola
            </Text>
            <TextInput
              {...tid("login-password")}
              ref={parolaRef}
              accessibilityLabel="Parola"
              accessibilityLabelledBy="giris-parola-etiket"
              style={stiller.girdi}
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
              autoComplete="current-password"
              textContentType="password"
              returnKeyType="go"
              onSubmitEditing={submit}
            />
          </View>
          {error && <Uyari {...tid("login-error")} tur="hata" metin={error} />}
          <Dugme
            {...tid("login-submit")}
            metin={busy ? "Giriş yapılıyor…" : "Giriş yap"}
            onPress={submit}
            devreDisi={!gonderilebilir}
            blok
          />
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const stiller = StyleSheet.create({
  kok: { flex: 1, backgroundColor: renk.bg },
  kaydirma: { padding: 16, paddingBottom: 48 },
  kart: { gap: 12 },
  marka: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 },
  markaMetin: { fontSize: 16, fontWeight: "700", color: renk.text },
  alan: { gap: 6 },
  etiket: { fontSize: 14, fontWeight: "600", color: renk.text },
  girdi: {
    minHeight: 44,
    borderWidth: 1,
    borderColor: renk.border,
    borderRadius: RADIUS - 2,
    paddingHorizontal: 12,
    fontSize: 16,
    color: renk.text,
    backgroundColor: renk.surface,
  },
});
