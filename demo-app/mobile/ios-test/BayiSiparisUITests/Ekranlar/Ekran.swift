import XCTest

/// Ekran nesnelerinin tabanı: platformdan bağımsız, kimlik sabitleriyle çalışan yardımcılar
/// (Java karşılığı: e2e-app ekranlar/Ekran.java).
///
/// Sözleşme (TASARIM §3.4, sembol tablosu `worker/diller/swift.py`): `Ekran`'dan türeyen sınıfların
/// `private`/`fileprivate` olmayan örnek metotları sembol tablosuna girer — eylem (fiil, dönüşsüz) ya
/// da beklenti (`dogrula` ön eki, dönüşsüz); parametreler yalnız `String`, `Int`, `Double`, `Bool`.
/// Bu sınıfın yardımcıları tabanda durduğu için tabloya girmez (alt sınıflar `final` ve yardımcı
/// tanımlamaz; gerekirse `private`).
///
/// Hata iletileri iki işaretle başlar (triage `triage/diller/swift.py` bunlara bakar):
/// `[TP-EYLEM]` eylem ön koşulu sağlanmadı (öğe yok, dokunulamıyor) ve `[TP-BEKLENTI]` beklenti
/// sağlanmadı (defect adayı). Metin karşılaştırması web'deki `toHaveText` gibi boşlukları
/// sadeleştirir (NBSP dahil).
class Ekran {
    static let eylemIsareti = "[TP-EYLEM]"
    static let beklentiIsareti = "[TP-BEKLENTI]"
    private static let yok = "(öğe yok)"

    let oturum: UygulamaOturumu

    required init(oturum: UygulamaOturumu) {
        self.oturum = oturum
    }

    final var app: XCUIApplication { oturum.app }

    // ------------------------------------------------------------------ bulma

    private func sorgu(_ kok: XCUIElement?, _ kimlik: String) -> XCUIElementQuery {
        (kok ?? app).descendants(matching: .any).matching(identifier: kimlik)
    }

    private func ilkGorunur(_ kapsayici: String?, _ kimlik: String) -> XCUIElement? {
        let kokler: [XCUIElement?]
        if let kapsayici {
            kokler = sorgu(nil, kapsayici).allElementsBoundByIndex
        } else {
            kokler = [nil]
        }
        for kok in kokler {
            for e in sorgu(kok, kimlik).allElementsBoundByIndex where e.exists && !e.frame.isEmpty {
                return e
            }
        }
        return nil
    }

    /// Öğeyi beklemeden bir kez arar (gerekirse bir kez kaydırır); bulunamazsa nil.
    final func hemenBul(_ kapsayici: String?, _ kimlik: String) -> XCUIElement? {
        if let e = ilkGorunur(kapsayici, kimlik), e.isHittable {
            return e
        }
        if let e = ilkGorunur(kapsayici, kimlik) {
            // Öğe ağaçta ama ekran dışında: kaydırarak getir.
            for _ in 0..<4 where !e.isHittable {
                app.swipeUp()
            }
            return e
        }
        return nil
    }

    private static func ad(_ kapsayici: String?, _ kimlik: String) -> String {
        kapsayici.map { "'\($0)' içinde '\(kimlik)'" } ?? "'\(kimlik)'"
    }

    /// Koşul sağlanana kadar bekler; sağlanmazsa testi `[TP-EYLEM]` iletisiyle durdurur.
    @discardableResult
    final func kosul<T>(
        _ aciklama: String, zaman: TimeInterval = 15, file: StaticString = #filePath,
        line: UInt = #line, _ dene: () -> T?
    ) -> T? {
        let son = Date().addingTimeInterval(zaman)
        repeat {
            if let deger = dene() {
                return deger
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        } while Date() < son
        XCTFail("\(Ekran.eylemIsareti) \(aciklama)", file: file, line: line)
        return nil
    }

    /// Beklenen değeri görene kadar bekler; görmezse `[TP-BEKLENTI]` iletisiyle testi durdurur.
    final func dogrula(
        _ konu: String, beklenen: String, zaman: TimeInterval = 10, file: StaticString = #filePath,
        line: UInt = #line, goruleni: () -> String, _ tamam: () -> Bool
    ) {
        let son = Date().addingTimeInterval(zaman)
        repeat {
            if tamam() {
                return
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        } while Date() < son
        XCTFail(
            "\(Ekran.beklentiIsareti) \(konu): beklenen \"\(beklenen)\", görülen \"\(goruleni())\"",
            file: file, line: line)
    }

    /// Öğe görünür olana kadar (gerekirse kaydırarak) bekler.
    @discardableResult
    final func gorunurBekle(_ kimlik: String, kapsayici: String? = nil) -> XCUIElement? {
        kosul("öğe görünmedi: kimlik \(Ekran.ad(kapsayici, kimlik))") { hemenBul(kapsayici, kimlik) }
    }

    /// İki öğeden biri görünene kadar bekler (web: `expect(a.or(b)).toBeVisible()`).
    final func biriGorunurBekle(_ kimlik1: String, _ kimlik2: String) {
        kosul("öğe görünmedi: kimlik '\(kimlik1)' ya da '\(kimlik2)'") {
            ilkGorunur(nil, kimlik1) != nil || ilkGorunur(nil, kimlik2) != nil ? true : nil
        }
    }

    // ------------------------------------------------------------------ eylemler

    /// Öğeye dokunur (görünür ve etkin olmasını bekler).
    final func dokun(_ kimlik: String, kapsayici: String? = nil) {
        let e = kosul("öğe dokunulabilir olmadı: kimlik \(Ekran.ad(kapsayici, kimlik))") { () -> XCUIElement? in
            guard let g = hemenBul(kapsayici, kimlik), g.isEnabled, g.isHittable else { return nil }
            return g
        }
        e?.tap()
    }

    /// Alana metin yazar (önce temizler), sonra ekran klavyesini kapatır.
    /// İlk açılışta yazılım klavyesi tuş düşürebilir: düz metin alanında yazılan değer okunur,
    /// tutmazsa temizlenip yeniden yazılır (en çok 3 deneme). Parola alanı okunamaz (maskeli).
    final func yaz(_ kimlik: String, _ metin: String) {
        guard let e = gorunurBekle(kimlik) else { return }
        for deneme in 1...3 {
            e.tap()
            if let mevcut = e.value as? String, !mevcut.isEmpty, mevcut != e.placeholderValue {
                e.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: mevcut.count))
            }
            e.typeText(metin)
            if e.elementType == .secureTextField || (e.value as? String) == metin {
                break
            }
            if deneme == 3 {
                XCTFail("\(Ekran.eylemIsareti) alana yazılamadı: kimlik '\(kimlik)'")
            }
        }
        klavyeyiKapat()
    }

    private func klavyeyiKapat() {
        guard app.keyboards.count > 0 else { return }
        for ad in ["Return", "Done", "Bitti", "Git", "return", "done"] {
            let b = app.keyboards.buttons[ad]
            if b.exists && b.isHittable {
                b.tap()
                return
            }
        }
        // Sayı klavyesinde dönüş tuşu yok: ekranın üst kenarına dokun (odak düşer).
        app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.06)).tap()
    }

    // ------------------------------------------------------------------ metin

    /// Boşlukları sadeleştirir: NBSP / dar NBSP → boşluk, ardışık boşluk → tek, baş/son kırpılır.
    static func sade(_ s: String?) -> String {
        guard let s else { return "" }
        let duz = s.replacingOccurrences(of: "\u{00A0}", with: " ")
            .replacingOccurrences(of: "\u{202F}", with: " ")
        return duz.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }

    private static func kendiMetni(_ e: XCUIElement) -> String {
        let etiket = sade(e.label)
        if !etiket.isEmpty {
            return etiket
        }
        if let v = e.value as? String {
            return sade(v)
        }
        return ""
    }

    /// Öğenin görünen metni: kendi metni, yoksa alt öğelerin metinleri (RN'de testID bir View'da ise
    /// metin alt Text öğesindedir).
    final func metin(_ e: XCUIElement) -> String {
        let kendi = Ekran.kendiMetni(e)
        return kendi.isEmpty ? altMetinler(e) : kendi
    }

    /// Öğenin ve alt öğelerinin metinleri (web: `toContainText` kapsamı).
    final func tumMetin(_ e: XCUIElement) -> String {
        Ekran.sade(Ekran.kendiMetni(e) + " " + altMetinler(e))
    }

    private func altMetinler(_ e: XCUIElement) -> String {
        var parcalar: [String] = []
        for alt in e.descendants(matching: .staticText).allElementsBoundByIndex {
            let t = Ekran.kendiMetni(alt)
            if !t.isEmpty && !parcalar.contains(t) {
                parcalar.append(t)
            }
        }
        return Ekran.sade(parcalar.joined(separator: " "))
    }

    private func gorulenMetin(_ kimlik: String, tum: Bool = false) -> String {
        guard let e = hemenBul(nil, kimlik) else { return Ekran.yok }
        return tum ? tumMetin(e) : metin(e)
    }

    // ------------------------------------------------------------------ beklentiler

    /// Öğenin metni tam olarak beklenen (sadeleştirilmiş) olmalı.
    final func metinOlmali(_ kimlik: String, _ beklenen: String, file: StaticString = #filePath, line: UInt = #line) {
        let b = Ekran.sade(beklenen)
        dogrula("'\(kimlik)' metni", beklenen: b, file: file, line: line,
                goruleni: { gorulenMetin(kimlik) }) { gorulenMetin(kimlik) == b }
    }

    /// Öğenin metni düzenli ifadeye tam uymalı.
    final func metinKalibinaUymali(_ kimlik: String, _ kalip: String) {
        dogrula("'\(kimlik)' metni", beklenen: "/\(kalip)/", goruleni: { gorulenMetin(kimlik) }) {
            gorulenMetin(kimlik).range(of: "^(?:\(kalip))$", options: .regularExpression) != nil
        }
    }

    /// Öğenin metni beklenen parçayı içermeli.
    final func metinIcermeli(_ kimlik: String, _ parca: String) {
        let p = Ekran.sade(parca)
        dogrula("'\(kimlik)' metni", beklenen: "… \(p) …", goruleni: { gorulenMetin(kimlik) }) {
            gorulenMetin(kimlik).contains(p)
        }
    }

    /// Öğe ve alt öğelerinin metni beklenen parçayı içermeli (ör. ürün kartında kampanya adı).
    final func tumMetinIcermeli(_ kimlik: String, _ parca: String) {
        let p = Ekran.sade(parca)
        dogrula("'\(kimlik)' içeriği", beklenen: "… \(p) …", goruleni: { gorulenMetin(kimlik, tum: true) }) {
            gorulenMetin(kimlik, tum: true).contains(p)
        }
    }

    /// Öğe görünür olmalı.
    final func gorunurOlmali(_ kimlik: String) {
        dogrula("'\(kimlik)' görünürlüğü", beklenen: "görünür", goruleni: { Ekran.yok }) {
            hemenBul(nil, kimlik) != nil
        }
    }

    /// Öğe ekranda olmamalı (web: `toHaveCount(0)`).
    final func yokOlmali(_ kimlik: String) {
        dogrula("'\(kimlik)' yokluğu", beklenen: Ekran.yok, goruleni: { "görünür" }) {
            ilkGorunur(nil, kimlik) == nil
        }
    }

    /// Öğe etkin (true) ya da pasif (false) olmalı.
    final func etkinOlmali(_ kimlik: String, _ etkin: Bool) {
        dogrula(
            "'\(kimlik)' durumu", beklenen: etkin ? "etkin" : "pasif",
            goruleni: { hemenBul(nil, kimlik).map { $0.isEnabled ? "etkin" : "pasif" } ?? Ekran.yok }
        ) { hemenBul(nil, kimlik)?.isEnabled == etkin }
    }

    /// Önek kimliğe sonek ekler (`Katalog.urunKartiOnek` + "P-001").
    static func ekli(_ onek: String, _ sonek: String) -> String {
        precondition(onek.hasSuffix("-"), "'\(onek)' önek kimlik değil ('-' ile bitmeli)")
        precondition(!sonek.trimmingCharacters(in: .whitespaces).isEmpty, "'\(onek)' için sonek gerekli")
        return onek + sonek
    }
}
