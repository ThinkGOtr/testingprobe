// Erişilebilirlik kimliği yardımcısı — locator sözleşmesi (specs/009-mobil-masaustu/plan.md §2.2).
//
// Kimlik değerleri web'deki data-testid değerlerinin AYNISIDIR (tek liste: demo-app/kimlikler.json;
// `npm run kimlik-kontrol` mobil kaynağın listeyle birebir uyduğunu denetler).
//
// Neden `testID` (ve accessibilityLabel değil)?
// - iOS: RN `testID` → UIView.accessibilityIdentifier → XCUITest `identifier` (Appium accessibilityId).
// - Android (RN 0.88, Fabric): BaseViewManager `testID`'yi R.id.react_test_id etiketine yazar;
//   etiket varken ReactAccessibilityDelegate kurulur ve onInitializeAccessibilityNodeInfo içinde
//   `info.viewIdResourceName = testId` yapılır → UiAutomator2'de `resource-id` (Appium id).
//
// Neden `collapsable: false`?
// - Fabric (iOS + Android) testID'li View'ı yerel görünüm olarak oluşturur (formsView) ama
//   "yığın bağlamı" (formsStackingContext) kurmaz: çocukları en yakın yığın bağlamlı ataya taşınır.
//   Sonuç: erişilebilirlik ağacında `product-card-P-001` BOŞ bir kardeş olur, "Sepete ekle" kartın
//   içinde aranamaz (web'deki `within` sözleşmesi bozulur). Gözlendi: RN 0.88, uiautomator dump.
//   `collapsable={false}` yığın bağlamını zorlar → kimlikli kapsayıcının çocukları gerçekten onun
//   altında kalır (iOS'ta da aynı). Text/TextInput/Pressable için etkisizdir.
// - accessibilityLabel'ı kimliğe eşitlemiyoruz: ekran okuyucu kullanıcıya "login-username" okur ve
//   gerçek erişilebilirliği bozar. Etiketler Türkçe ve anlamlı kalır (Kullanıcı adı, Sepete ekle…).
//
// Kısıt (iOS): `accessible` olan bir elemanın (Pressable, Text) çocukları XCUITest'te tek elemana
// katlanır; bu yüzden kimlik taşıyan elemanlar dokunulabilir başka bir elemanın İÇİNE konmaz
// (ör. sepet sayacı `cart-count`, `nav-cart` düğmesinin kardeşidir, çocuğu değil).
// Kısıt (her iki platform): iç içe <Text> (span) kendi görünümünü oluşturmaz; kimlikli metin
// her zaman en dıştaki <Text>'tir.

export interface KimlikOzellikleri {
  testID: string;
  collapsable: false;
}

/** Kimlik: `{...tid("login-username")}`, dinamik: `{...tid(`product-card-${kod}`)}`. */
export function tid(id: string): KimlikOzellikleri {
  return { testID: id, collapsable: false };
}
