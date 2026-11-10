import { StatusBar } from "expo-status-bar";
import { useCallback, useEffect, useRef, useState } from "react";
import { BackHandler, StyleSheet, Text, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { api, setUnauthorizedHandler, type Cart, type User } from "./api";
import { Kabuk } from "./bilesenler/Kabuk";
import { GirisEkrani } from "./ekranlar/GirisEkrani";
import { KatalogEkrani } from "./ekranlar/KatalogEkrani";
import { OnayEkrani } from "./ekranlar/OnayEkrani";
import { SepetEkrani } from "./ekranlar/SepetEkrani";
import { SiparislerEkrani } from "./ekranlar/SiparislerEkrani";
import { ayniEkran, type Ekran } from "./gezinti";
import { renk } from "./tema";

// Kural (web ile aynı): her etkileşimli / doğrulanan elemanda kimlik bulunur; değerler
// demo-app/kimlikler.json'daki web data-testid'leridir (bkz. src/kimlik.ts, scripts/kimlik-kontrol.mjs).
export default function App() {
  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      <Uygulama />
    </SafeAreaProvider>
  );
}

function Uygulama() {
  // undefined: oturum kontrol ediliyor · null: giriş yapılmamış
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [cart, setCart] = useState<Cart | null>(null);
  const [yigin, setYigin] = useState<Ekran[]>([{ ad: "katalog" }]);
  const yiginRef = useRef(yigin);
  yiginRef.current = yigin;
  const ekran = yigin[yigin.length - 1];

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null);
      setCart(null);
    });
    api
      .session()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  useEffect(() => {
    if (user) api.cart().then(setCart).catch(() => setCart(null));
    // Oturum değişince (giriş/çıkış) web'deki gibi kataloğa dönülür.
    setYigin([{ ad: "katalog" }]);
  }, [user]);

  const git = useCallback((hedef: Ekran) => {
    const y = yiginRef.current;
    if (ayniEkran(y[y.length - 1], hedef)) return;
    // Hedef yığında zaten varsa oraya geri sarılır (yığın sınırsız büyümez); yoksa üstüne eklenir.
    // Geri tuşu bir önceki ekrana döner.
    const i = y.findIndex((e) => ayniEkran(e, hedef));
    setYigin(i >= 0 ? y.slice(0, i + 1) : [...y, hedef]);
  }, []);

  // Android geri tuşu: yığında önceki ekran varsa ona dön, yoksa sistem davranışı (uygulamadan çık).
  useEffect(() => {
    const abonelik = BackHandler.addEventListener("hardwareBackPress", () => {
      if (!user || yiginRef.current.length <= 1) return false;
      setYigin((y) => y.slice(0, -1));
      return true;
    });
    return () => abonelik.remove();
  }, [user]);

  const onCartChange = useCallback((c: Cart) => setCart(c), []);

  async function logout() {
    try {
      await api.logout();
    } catch {
      // Web ile aynı: çıkış isteği başarısız olsa da yerel oturum kapatılır.
    } finally {
      setUser(null);
      setCart(null);
    }
  }

  if (user === undefined) {
    return (
      <View style={stiller.acilis}>
        <Text style={stiller.acilisMetin} accessibilityRole="progressbar">
          Yükleniyor…
        </Text>
      </View>
    );
  }
  if (user === null) return <GirisEkrani onLoggedIn={setUser} />;

  let sayfa;
  switch (ekran.ad) {
    case "katalog":
      sayfa = <KatalogEkrani onCartChange={onCartChange} />;
      break;
    case "sepet":
      sayfa = <SepetEkrani cart={cart} onCartChange={onCartChange} git={git} />;
      break;
    case "siparisler":
      sayfa = <SiparislerEkrani git={git} />;
      break;
    case "siparis":
      sayfa = <OnayEkrani key={ekran.numara} numara={ekran.numara} git={git} />;
      break;
  }

  return (
    <Kabuk user={user} cartCount={cart?.adet_toplam ?? 0} ekran={ekran} git={git} onLogout={logout}>
      {sayfa}
    </Kabuk>
  );
}

const stiller = StyleSheet.create({
  acilis: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: renk.bg },
  acilisMetin: { color: renk.muted, fontSize: 15 },
});
