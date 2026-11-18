# 014 Test dilleri — sözleşme (Ş0 çekirdek soyutlama)

Tarih: 2026-11-18. Kaynak tasarım: `aip-review/test-dilleri/TASARIM.md` §1.3, §2, §3, §4.2.
Bu doküman paralel şeritlerin (Ş1 Python, Ş2 C#, Ş3 Kotlin, Ş4 Swift, Ş5 müşteri CI, Ş7 portal,
Ş8 değerlendirme kapısı) yazdığı eklentilerin **tek sözleşmesidir**. Ş0 burada yazılanı uygular;
sapma görülürse şerit kendi dosyasında geçici adaptör yazar ve raporuna "Ş0'a not" düşer.

Kesin kararlar (kullanıcı, 2026-11-18): (1) iskelet/PO kütüphanesi/CI yoksa insan onaylı tek seferlik
kurulum PR'ı; TP `project.pbxproj`'a dokunmaz. (2) Espresso/XCUITest v1 yalnız GitHub Actions; yeşil
CI merge için yeterli, PR ve portalda "kırarak doğrulanmadı" rozeti. (3a) Doğrulanmamış web C#/Python
üretimi değerlendirme geçene kadar KAPALI; (3b) TS/Java açık. (4) Dil platform başına seçilir;
değerlendirmeden geçmemiş çift "Yakında" (seçilemez); tek kaynak `rules/diller.yaml`.

---

## 1. Matris ve tek kaynak (`core/src/tp_core/features/codegen/platform.py`)

```python
Dil = Literal["ts", "java", "csharp", "python", "kotlin", "swift"]
Hat = Literal["tam", "musteri_ci", "dogrulanmamis"]
Sonuc = Literal["junit", "playwright-json", "surefire"]
Ajan = Literal["verify_and_map", "verify_and_map_app"]

@dataclass(frozen=True)
class Cati:
    platform: str            # web | android | ios | windows
    dil: str                 # Dil
    hat: Hat
    etiket: str              # görünen çatı adı ("pytest + Appium")
    sablon: str              # rules/templates altındaki Jinja dosyası
    kok_ayari: str           # test projesi kökünün env adı (bkz. §4)
    kok_varsayilan: str      # uygulama köküne göre varsayılan ("e2e-app-python")
    uretilen_alt_yol: str    # proje köküne göre üretilen testlerin dizini
    sonuc: Sonuc             # koşu sonucu biçimi
    ajan: Ajan               # platformdan: web → verify_and_map, uygulama → verify_and_map_app
    gh_is_akisi: str | None  # GitHub iş akışı/check adı ("web-python", "mobil-android-kotlin")

    @property
    def check(self) -> str          # check_adi(platform, dil)
    @property
    def anahtar(self) -> str        # "web/python" (diller.yaml anahtarı)

CATILAR: dict[tuple[str, str], Cati]   # TEK KAYNAK; gecerli_cift(p, d) == (p, d) in CATILAR
```

| (platform, dil) | hat | etiket | sablon | kok_ayari | kok_varsayilan | uretilen_alt_yol | sonuc | gh_is_akisi |
|---|---|---|---|---|---|---|---|---|
| web/ts | tam | Playwright Test | playwright_test.ts.j2 | TP_E2E_ROOT | e2e | tests/generated | playwright-json | ci (check `local-ci`) |
| web/java | tam | Playwright for Java + TestNG | playwright_testng.java.j2 | TP_E2E_JAVA_ROOT | e2e-java | src/test/java/com/antreklabs/bayi/uretilen | surefire | web-java |
| android/java, ios/java, windows/java | tam | Appium + TestNG | appium_testng.java.j2 | TP_E2E_APP_ROOT | e2e-app | (aynı) | surefire | mobil-android / mobil-ios / masaustu-windows |
| web/python | tam | pytest + Playwright | playwright_pytest.py.j2 | TP_E2E_PYTHON_ROOT | e2e-python | tests/generated | junit | web-python |
| android/python, ios/python, windows/python | tam | pytest + Appium | appium_pytest.py.j2 | TP_E2E_APP_PYTHON_ROOT | e2e-app-python | tests/generated | junit | mobil-android-python / mobil-ios-python / masaustu-windows-python |
| web/csharp | tam | Playwright .NET + NUnit | playwright_nunit.cs.j2 | TP_E2E_CSHARP_ROOT | e2e-csharp | tests/Generated | junit | web-csharp |
| windows/csharp | tam | Appium .NET + NUnit (NovaWindows) | appium_nunit.cs.j2 | TP_E2E_APP_CSHARP_ROOT | e2e-app-csharp | tests/Generated | junit | masaustu-windows-csharp |
| android/kotlin | musteri_ci | Espresso (AndroidX Test, JUnit4) | espresso_junit.kt.j2 | TP_ANDROID_KOTLIN_ROOT | app/src/androidTest/java | tp/uretilen | junit | mobil-android-kotlin |
| ios/swift | musteri_ci | XCUITest | xcuitest.swift.j2 | TP_IOS_SWIFT_ROOT | UITests | TPUretilen | junit | mobil-ios-swift |

Sıralı sabitler: `DILLER = ("ts", "java", "csharp", "python", "kotlin", "swift")` (algılama eşitlik
önceliği bu sıradır), `HATLAR`, `DIL_ETIKETI` (6 dil). `TAM_HAT_DILLERI` ve `DOGRULANMAMIS_DILLER`
geriye uyum için kalır ama **yeni kod `hat(p, d)` sorar**.

Yardımcılar (hepsi saf):

| İşlev | Anlam |
|---|---|
| `cati_bul(p, d) -> Cati \| None` | matristen kayıt |
| `hat(p, d) -> Hat \| None` | çiftin hattı |
| `gecerli_cift(p, d)`, `platform_dilleri(p)`, `gecerli_dil(p, d)` | matristen |
| `varsayilan_dil(p)` | web → ts, uygulama → java (değişmez) |
| `check_adi(p, d)` | web+ts `local-ci`; web+java `local-ci-web-java`; uygulama+java `local-ci-<p>`; diğer `local-ci-<p>-<d>` |
| `gh_check_adi(p, d)` | `cati.gh_is_akisi` (GitHub kipinde zorunlu check adı) |
| `tam_hat_mi(d, p=None)` | p verilirse `hat(p,d) == "tam"`; verilmezse geriye uyum (`d in ("ts","java")`) |
| `musteri_ci_mi(p, d)` | `hat(p, d) == "musteri_ci"` |
| `cift_durumu(p, d) -> "acik" \| "yakinda"` | `rules/diller.yaml` (Ş8) okunur; dosya yoksa/okunamazsa ts/java çiftleri `acik`, diğerleri `yakinda` |

Eski adlar (`java_mi`, `uygulama_mi`, `java_eslemesi`, `JAVA_*`, `E2E_*_DIZINI`, `e2e_kokleri`,
`repodaki_web_dilleri`, `degisen_web_dilleri`) davranışları değişmeden kalır.

### 1.1 Seçilebilirlik kuralı (TP kendi kapısını uygular)

Bir (p, d) çifti `POST /code/generate` ve `GET /code/languages` için **kullanılabilir** ⇔

1. `(p, d) in CATILAR`;
2. `cift_durumu(p, d) == "acik"` (değilse neden: `"Değerlendirme sürüyor"` = Ş8 `dil_kapisi.YAKINDA_NEDENI`, 422; kaynak
   `dil_kapisi.kullanilabilir_mi`, modül yoksa yerel yedek);
3. çekirdek dil eklentisi kayıtlı (`codegen.diller.eklenti(d)` var; değilse aynı "Yakında" nedeni);
4. proje ayarı izin veriyor: web için `TP_WEB_DILLERI`, uygulamada `TP_DILLERI_<P>` (boş = yalnız
   platform varsayılanı); bugünkü K-T3 kuralı (GitHub kipinde java yalnız listedeyse) tüm çiftlere
   genelleşir. Varsayılan dil (web/ts, uygulama/java) liste boşken her zaman izinlidir;
5. repoda o dilin test projesi var (dil eklentisinin `proje_dosyasi`) — yoksa bugünkü "proje yok"
   nedeni; Ş5 kurulum PR'ı akışı bu nedeni okur.

`GET /code/languages` her seçenekte şu alanları döndürür (Ş7 portal aynası):

```json
{"dil": "python", "etiket": "Python", "cati": "pytest + Playwright",
 "hat": "tam|musteri_ci|dogrulanmamis", "durum": "acik|yakinda",
 "kirarak_dogrulama": true, "check": "local-ci-web-python",
 "kurulum": null, "kullanilabilir": false, "neden": "Değerlendirme sürüyor"}
```

`kirarak_dogrulama` yalnız `hat == "tam"` iken `true`'dur (musteri_ci: "kırarak doğrulanmadı" rozeti).

---

## 2. Çekirdek dil eklentisi (`core/src/tp_core/features/codegen/diller/<dil>.py`)

Keşif: `codegen/diller/__init__.py` paketi `pkgutil.iter_modules` ile tarar; her modül modül
düzeyinde `EKLENTI` nesnesi tanımlar (`DilEklentisi` protokolü). Merkezi listeye satır eklenmez.
`_` ile başlayan modüller atlanır. Yükleme hatası olan modül atlanır ve uyarı loglanır (bir dilin
hatası diğerlerini düşürmez); `diller.hatalar()` bunları döndürür (birim testleri boş bekler).

```python
class DilEklentisi(Protocol):
    ad: str                                   # "python" (dosya adıyla aynı)
    proje_dosyasi: str                        # proje köküne göre: "pyproject.toml", "pom.xml", "package.json", "*.csproj"
    algila_kaliplari: tuple[AlgilaKalibi, ...]

    def render(self, inp: RenderInput, cati: Cati, rules: Path, *,
               referans_dil: str | None = None,
               sembol_tablosu: Mapping[str, Any] | None = None) -> Rendered: ...
    def literal(self, value: Any) -> str: ...           # dil literal süzgeci (şablonda)
    def ident(self, value: Any) -> str: ...             # güvenli tanımlayıcı
    def sinif_adi(self, story_key: str | None, platform: str, sira_no: int,
                  case_id: uuid.UUID) -> str | None: ...# sınıf adı (yoksa None: pytest/ts)
    def uretilen_yol(self, cati: Cati, kok: str, story_key: str | None, sira_no: int,
                     case_id: uuid.UUID) -> str: ...    # forge'daki tam depo yolu
    def test_dosyasi_mi(self, yol: str) -> bool: ...    # elle yazılmış test mi (kökten bağımsız)
    def eslemeyi_donustur(self, output: Any) -> Any: ...# ajan çıktısındaki TS metot adlarını dile çevirir

@dataclass(frozen=True)
class AlgilaKalibi:
    platformlar: frozenset[str]   # hangi platformlarda sayılır
    kok_ayari: str                # Cati.kok_ayari (hangi kökün altında aranır)
    alt_dizin: str                # kökün altındaki arama dizini ("tests/", "src/test/java/")
```

- İsteğe bağlı kancalar (yoksa atlanır): `bayiler_alt_yolu: str` (dil köküne göre bayi dosyası,
  ör. Swift `Altyapi/Bayiler.swift`) ve `parse_dealers(kaynak) -> {bayi: {...}}`. Yalnız referans
  ts/java projesi yokken (tablo hedef dilin kendisi) kullanılır; referans varsa bayiler ve
  denetim tablosu referanstan gelir ve render'a `referans_dil` + `sembol_tablosu` (o tablonun
  `/symbols` çıktısı) geçer.
- `Rendered` (render.py) değişmez; yeni alanlar yalnız isteğe bağlıdır. `Rendered.dil` = eklenti adı.
- Render hatası `render.RenderError`. Sır sızıntısı denetimi (`render._sizinti_tara`) her eklentide
  çağrılmalıdır (ortak yardımcı: `diller.ortak.sizinti_tara(content, inp)`).
- Model kod yazmaz: şablon + literal süzgeçleri. Ajan eşlemesi TS (ya da Java) adlarıyla gelir;
  `eslemeyi_donustur` ad kuralını uygular (python snake_case, csharp PascalCase+`Async`,
  kotlin/swift camelCase; java `goto → goTo`).
- `render.render_dil(...)` tek giriş noktası kalır: önce matris denetimi, sonra
  `diller.eklenti(dil).render(inp, cati_bul(platform, dil), rules, ...)`. Eklenti yoksa ve dil
  `csharp|python` ise eski doğrulanmamış render'a düşer (geçmiş kayıtlar; yeni üretim zaten kapalı).
- ts/java eklentileri (`diller/ts.py`, `diller/java.py`) Ş0'dadır ve bugünkü render işlevlerini
  çağırır; çıktı bayt eşittir (golden testleri).

### 2.1 Triage eklentisi (`core/src/tp_core/features/triage/diller/<dil>.py`)

Aynı keşif deseni (`EKLENTI`, `triage.diller.eklenti(d)`):

```python
class TriageEklentisi(Protocol):
    ad: str
    def hata_turu(self, mesaj: str, istisna: str | None = None) -> str | None: ...
        # `Sinyal.tur()` sözlüğü: "locator_timeout" | "locator_not_found" | "assertion" |
        # "navigation" | "test_data" | "other" | "derleme" | None (= ortak kurallara düş)
    def beklenen_gorulen(self, mesaj: str | None) -> tuple[str | None, str | None]: ...
    def test_kimligi(self, test_adi: str, dosya: str | None) -> str | None: ...
        # script eşleme anahtarı: case u8 ("<Sinif>C<sira>_<u8>Test" / "test_<slug>_<u8>") → "<u8>"
    def test_dosyasi_mi(self, dosya: str | None) -> bool: ...   # sinyal bu dile mi ait
```

`triage.rules.Sinyal.tur()` ts/java kurallarından sonra `dil` alanının eklentisine sorar
(`hata_turu`); `None` ise ortak kurallara düşer. Derleme hatası (musteri_ci: JUnit yok, iş adımı
kırmızı) türü `derleme`'dir; sınıflandırma `test_maintenance`.

---

## 3. Toolchain eklentileri

### 3.1 Worker (`toolchain/worker/diller/<dil>.py`)

Keşif `worker/diller/__init__.py` (aynı `EKLENTI` deseni). `lang` alanı `Literal` değildir; kayıtlı
eklenti adlarından doğrulanır (`diller.adlar()`); ts ve java da eklenti olarak kayıtlıdır.

```python
class WorkerDili(Protocol):
    ad: str
    platformlar: tuple[str, ...]     # ("web",) / ("android","ios","windows") ...
    steps: tuple[str, ...]           # /check adım sırası, ör. ("app","deps","guard","compile","run")
    hat: str                         # "tam" | "musteri_ci" (musteri_ci'de "run" adımı yoktur)

    def validate_test_file(self, yol: str) -> str: ...        # proje köküne göre; ValueError
    def symbols(self, cfg: Settings, full_sha: str, repo: Path, platform: str) -> dict: ...
        # §3.3 tablo biçimi; önbellek ve "sha"/"lang" eki çağıran tarafta
    def guard(self, cfg: Settings, repo: Path, base: str, head: str, mode: str,
              platform: str) -> dict: ...                    # {"ok", "violations", ...}
    def run_static(self, cfg: Settings, req: CheckRequest, head: repos.Located,
                   base: str | None, runner_client: httpx.Client | None,
                   steps: dict[str, dict]) -> dict[str, dict]: ...
        # adımları sırayla doldurur; tam hatta sonunda `checks._call_runner(cfg, body, client)`
        # ile test-runner'a {"lang": ad, "platform": p, ...} gönderir
```

Kök çözümü: `diller.kok(cfg, kok_ayari, varsayilan, platform)` → `cfg.dil_kokleri` (proje bloğu)
> `os.environ[<kok_ayari>_<P>]` > `os.environ[<kok_ayari>]` > varsayılan. Proje bloğu
(`ProjeBlogu.dil_kokleri: dict[str, str]`) anahtarları env adlarıdır (`TP_E2E_PYTHON_ROOT`, ...).

tree-sitter (kotlin/swift): imajda `/opt/dil-statik` (`pip --target`; ortak `tree-sitter==0.26.1`
satırı Ş0'da, dilbilgisi satırları şerit bloklarında). Eklenti içe aktarmadan önce
`worker.diller.statik_yolu_ekle(cfg)` çağırır.

Check adı: `worker.check.check_name(lang, platform)` core `check_adi` ile aynı kural
(`local-ci-<p>-<d>`); eşitlik `toolchain/tests/data/core_sozlesme.json`.

### 3.2 Runner (`toolchain/runner/diller/<dil>.py`)

```python
class RunnerDili(Protocol):
    ad: str
    def validate_test_file(self, yol: str) -> str: ...
    def execute_locked(self, cfg: Settings, req: RunRequest, loc: repos.Located,
                       http: httpx.Client | None) -> dict[str, Any]: ...
        # results.json biçimi bugünkü Java yoluyla aynı (tests[], failures[], status, saglik)
```

`RunBody.lang` kayıtlı runner eklentilerinden doğrulanır; `run._execute_locked` ts dışındaki dili
eklentiye dağıtır (java → `java_run`, Ş0'da eklenti sarmalayıcısıdır).

### 3.3 Sembol tablosu biçimi (tüm diller)

Bugünkü `tp-symbols` şeması korunur (`page_objects`, `fixtures`, ...); yeni diller ek olarak
normalleştirilmiş görünüm verebilir:

```json
{"lang": "python", "classes": [{"name": "LoginPage", "methods": [{"name": "login",
  "params": [{"name": "username", "type": "string"}], "kind": "action"}]}],
 "ids": [{"key": "LOGIN_SUBMIT", "testId": "login-submit", "intent": "...", "prefix": "..."}]}
```

Tür adları `string|int|long|double|boolean`. `page_objects` alanı zorunludur (çağıran bunu arar);
yeni diller `classes` → `page_objects` dönüşümünü kendi eklentisinde yapar.

---

## 4. Ortam değişkenleri (hepsi Ş0'da eklendi; dil şeritleri env/compose'a dokunmaz)

Proje kapsamlı (`proje/ayar.py` `_PROJE`, `home_config/durum.py`, `docker-compose.yml` ortak blok,
`.env.example`):

| Env | Anlam | Varsayılan |
|---|---|---|
| `TP_WEB_DILLERI` (var) | web dilleri `ts,java,python,csharp` | boş = ts |
| `TP_DILLERI_ANDROID` | android dilleri `java,python,kotlin` | boş = java |
| `TP_DILLERI_IOS` | ios dilleri `java,python,swift` | boş = java |
| `TP_DILLERI_WINDOWS` | windows dilleri `java,python,csharp` | boş = java |
| `TP_E2E_PYTHON_ROOT` | web Python test projesi | `e2e-python` |
| `TP_E2E_CSHARP_ROOT` | web C# test projesi | `e2e-csharp` |
| `TP_E2E_APP_PYTHON_ROOT` (+`_ANDROID/_IOS/_WINDOWS`) | uygulama Python projesi | `e2e-app-python` |
| `TP_E2E_APP_CSHARP_ROOT` (+`_WINDOWS`) | Windows C# projesi | `e2e-app-csharp` |
| `TP_ANDROID_KOTLIN_ROOT` (+`_ANDROID`) | Espresso kaynak kökü | `app/src/androidTest/java` |
| `TP_IOS_SWIFT_ROOT` (+`_IOS`) | XCUITest hedef klasörü (eşitlenmiş klasör) | `UITests` |

Kaplama kuralı (platform-depo `ProjeOrtami(pid, platform)`): `<kok_ayari> ← <kok_ayari>_<P> ?? taban`.
Ayrı platform deposunda Home anahtarı `tp.repos.<p>.test_root_<dil>` → env `<kok_ayari>_<P>`.

Toolchain (yalnız `toolchain-worker`/`test-runner` servisleri; `toolchain_common/settings.py`):

| Env | Anlam | Varsayılan |
|---|---|---|
| `TP_E2E_PYTHON_DEPS` | güvenilir kilit + venv (`/opt/e2e-python/venv`) | `/opt/e2e-python` |
| `TP_E2E_CSHARP_DEPS` | güvenilir `Directory.Packages.props` + NuGet önbelleği | `/opt/e2e-csharp` |
| `TP_CS_ARACLAR` | cs-araclar (Roslyn) çalıştırılabilir dizini | `/opt/cs-araclar` |
| `TP_DIL_STATIK` | tree-sitter (kotlin/swift) dilbilgileri dizini | `/opt/dil-statik` |
| `TP_DOTNET` | dotnet ikilisi | `/usr/share/dotnet/dotnet` |
| `TP_PYTHON_E2E` | e2e venv python ikilisi | `/opt/e2e-python/venv/bin/python` |
| `TP_PY_GUARD` | Ş1 py-guard betiği | `<TP_E2E_PYTHON_DEPS>/py-guard/py_guard.py` |
| `TP_PY_GUARD_PYTHON` | py-guard'ı koşan python (3.10+) | `/usr/bin/python3.12` |
| `TP_DIL_TIMEOUT_S` | yeni dillerin derleme/statik adım süre sınırı | `300` |

---

## 5. Toolchain imajı (`toolchain/Dockerfile`)

Ş0 üç boş, adlandırılmış aşama ve `ci` aşamasında COPY yerlerini koydu. Her şerit **yalnız kendi
işaretli bloğunu** düzenler (işaretler arası boş satır korunur; git ayrık parçaları temiz birleştirir):

- `# ==== dil-python (Ş1) ====` → `FROM base AS dil-python` … `/opt/e2e-python`
- `# ==== dil-csharp (Ş2) ====` → `FROM base AS dil-csharp` … `/opt/e2e-csharp`, `/opt/cs-araclar`,
  `/opt/dotnet` (Ş2 `FROM` satırını .NET SDK tabanına çevirebilir)
- `# ==== dil-statik (Ş3 Kotlin satırları / Ş4 Swift satırları) ====` → `FROM base AS dil-statik` …
  `/opt/dil-statik` (tree-sitter dilbilgileri; Ş3 ve Ş4 ayrı alt işaretlerin arasına yazar)
- `ci` aşamasında: `# ==== dil COPY (Ş1/Ş2/Ş3-4) ====` altında her şeridin kendi `COPY --from=dil-*`
  satırı vardır; şerit yalnız kendi satırına ek yapar (ör. duman testi `RUN`).

---

## 6. Veri modeli

- `models/enums.py`: `DIL` += `kotlin`, `swift`; yeni `HAT = {"tam", "musteri_ci", "dogrulanmamis"}`.
- Göç `core/alembic/versions/0047_dil_genisleme.py` (`down_revision = "0046"`): `script_dil_ck`
  CHECK'i 6 dile genişler. Downgrade yalnız kotlin/swift satırı yokken (aksi `RuntimeError`).
- Script durumu değişmez; musteri_ci hattının durum akışı Ş5'tedir (`features/musteri_ci/**`).

---

## 7. Zorunlu check'ler (forge)

- LocalForge: `forge.local_required_checks` yol kuralı (p, d) köklerine genişler: kökte değişiklik →
  `check_adi(p, d)` zorunlu. Musteri_ci çiftleri LocalForge'da yoktur (müşteri CI'ı yalnız GitHub).
- GitHub: `forge_github` zorunlu iş akışı listesi = mevcutlar + her açık ve env'de seçili (p, d)
  için `gh_check_adi(p, d)`; ayrı platform deposunda dil iş akışı o depoya aittir.

---

## 8. Şerit → dosya özeti (yalnız bunlar; ayrıntı TASARIM §4.2)

| Şerit | Eklenti dosyaları |
|---|---|
| Ş1 Python | `codegen/diller/python.py`, `triage/diller/python.py`, `worker/diller/python.py`, `runner/diller/python.py` |
| Ş2 C# | `codegen/diller/csharp.py`, `triage/diller/csharp.py`, `worker/diller/csharp.py`, `runner/diller/csharp.py` |
| Ş3 Kotlin | `codegen/diller/kotlin.py`, `triage/diller/kotlin.py`, `worker/diller/kotlin.py` (runner yok: musteri_ci) |
| Ş4 Swift | `codegen/diller/swift.py`, `triage/diller/swift.py`, `worker/diller/swift.py` (runner yok) |
| Ş8 | `rules/diller.yaml` (şema: `version: 1`, `ciftler: {"<p>/<d>": {durum: acik\|yakinda, kanit?: {...}}}`) |

Not: tasarımda runner dosya adı `<dil>_run.py` geçiyordu; keşif ad = dil kuralı için dosya
`runner/diller/<dil>.py` olur (ör. `runner/diller/python.py`). Eski ad kullanılırsa keşif modül
adını değil `EKLENTI.ad`'ı esas alır; ikisi de çalışır.
