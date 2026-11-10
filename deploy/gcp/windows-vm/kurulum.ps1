# tp-windows (GCP Windows Server 2022 Desktop Experience) kurulum betigi.
# Sozlesme: specs/009-mobil-masaustu/windows-gcp.md
#
# GCP metadata anahtari `windows-startup-script-ps1` olarak verilir; GCEMetadataScripts tarafindan
# SYSTEM hesabiyla, Windows PowerShell 5.1'de, HER ACILISTA calistirilir. Idempotenttir: tamamlanan
# adimlar C:\tp\durum\*.ok isaret dosyalarindaki anahtarla (surum / dosya ozeti) karsilastirilip atlanir;
# kod degismediyse ikinci ve sonraki acilislar yalnizca denetim + Appium beklemesinden ibarettir.
#
# Bu dosya BILEREK yalnizca ASCII'dir (Turkce karakter yok): metadata'dan yazilan betik BOM'suz gelir ve
# PowerShell 5.1 onu ANSI kod sayfasiyla okur; UTF-8 tire/ok gibi karakterler (E2 80 93 ...) cp1252'de
# "akilli tirnak"a donusup dize sozdizimini bozabilir. Statik test (test_windows_vm_kurulum_betigi.py)
# ASCII disi karakteri reddeder.
#
# Seri port (COM1): GCEMetadataScripts betigin stdout'unu satir satir seri port 1'e yazar (onune
# "windows-startup-script-ps1: " gibi bir onek ekleyerek). COM1'i betikten [System.IO.Ports.SerialPort]
# ile acmak ajanla cakisir (port ajanda acik), bu yuzden durum satirlari [Console]::Out ile stdout'a
# yazilir. Mac tarafi satiri ONEKTEN BAGIMSIZ (alt dize) aramalidir. Bicimler:
#   TP-WINDOWS-BASLADI ref=<ref>                                      (her acilisin ilk satiri)
#   TP-WINDOWS-ADIM <adim> <tamam|atlandi>                            (bilgi; zorunlu degil)
#   TP-WINDOWS-HAZIR appium=4723 uygulama=<yol> ref=<ref>
#   TP-WINDOWS-HATA <adim> <mesaj>
# Hicbir sir (parola) seri porta ya da log dosyalarina yazilmaz.
#
# Akis (her acilis):
#   metadata -> kaynak (codeload zip, yalnizca tools/appium + demo-app/desktop) -> node -> appium ->
#   dotnet -> uygulama -> kullanici (+ otomatik oturum) -> oturum-ayarlari -> guvenlik-duvari ->
#   gorev -> [ilk kurulumda bir kez yeniden baslatma] -> baslat-bayragi -> appium-bekle -> ekran -> HAZIR
#
# Oturum tarafi (C:\tp\betik\oturum.ps1, bu betik yazar): tpotomasyon oturum acinca zamanlanmis gorevle
# calisir; bu acilisin "baslat bayragini" (C:\tp\durum\baslat.txt = acilis zamani) bekler, ekran
# cozunurlugunu ayarlar, sonra Appium'u 0.0.0.0:4723'te baslatir. Bayrak sayesinde Appium, kurulum
# adimlari (npm ci / yayin) bitmeden baslamaz ve dosya kilidi yarisi olmaz.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest ilerleme cubugu 5.1'de indirmeyi cok yavaslatir
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ---------------------------------------------------------------------------------------------------
# Sabit surumler (degistirirken ozetleri resmi kaynaktan yeniden alin)
# ---------------------------------------------------------------------------------------------------
# Node.js 22 LTS (CI: masaustu-windows.yml NODE_VERSION "22"). Ozet: https://nodejs.org/dist/v22.23.4/SHASUMS256.txt
$NodeSurum = '22.23.4'
$NodeZipSha256 = 'cbc74b5e0982c9dbb41525fd8fb5dcd32fbee237863f7829072f4639a1ce5f20'
# .NET 8 SDK. Ozet (SHA512): https://dotnetcli.blob.core.windows.net/dotnet/release-metadata/8.0/releases.json
# dotnet-install.ps1 yerine resmi zip dogrudan indirilir: betik surekli degistigi icin ozetle
# sabitlenemez; zip'in SHA512'si ise surum meta verisinde yayinlanir.
$DotnetSdkSurum = '8.0.427'
$DotnetSdkZipSha512 = 'a4dd6eb2bf2a2f6fb10997d3e044a229b23ad96a5c86d20494687e34ee73b537d7bd14488ce14cded6917f6778da4d66360e2734020b7ef487d0f29ab144489d'
# Appium 3.9.0 tools/appium/package-lock.json'dan gelir (npm ci). NovaWindows kilit dosyasinda yok
# (yalniz Windows'ta calisir); CI ile ayni tam surum: masaustu-windows.yml NOVAWINDOWS_VERSION.
$NovaWindowsSurum = '1.5.0'

# ---------------------------------------------------------------------------------------------------
# Yollar ve sabitler
# ---------------------------------------------------------------------------------------------------
$Kok = 'C:\tp'
$DurumDizini = Join-Path $Kok 'durum'          # isaret dosyalari (yalniz SYSTEM/yonetici yazar)
$LogDizini = Join-Path $Kok 'log'              # tpotomasyon da yazar (appium.log, oturum.log)
$OturumDizini = Join-Path $Kok 'oturum'        # tpotomasyon yazar (ekran.txt)
$IndirDizini = Join-Path $Kok 'indir'
$AracDizini = Join-Path $Kok 'araclar'
$KaynakDizini = Join-Path $Kok 'kaynak'        # depodan yalnizca gereken alt agaclar
$BetikDizini = Join-Path $Kok 'betik'
$AppiumHome = Join-Path $Kok 'appium'          # APPIUM_HOME (sozlesme)
$UygulamaDizini = Join-Path $Kok 'uygulama'
$UygulamaExe = Join-Path $UygulamaDizini 'BayiSiparis.exe'
$NodeDizini = Join-Path $AracDizini "node-v$NodeSurum-win-x64"
$DotnetDizini = Join-Path $AracDizini "dotnet-sdk-$DotnetSdkSurum"
$OturumBetigi = Join-Path $BetikDizini 'oturum.ps1'
$BaslatBayragi = Join-Path $DurumDizini 'baslat.txt'
$EkranDosyasi = Join-Path $OturumDizini 'ekran.txt'
$Kullanici = 'tpotomasyon'
$GorevAdi = 'TP Appium'
$KuralAdi = 'TP-Appium-4723'
$AppiumPort = 4723
$EkranMinGenislik = 1440
$EkranMinYukseklik = 900
$AppiumBeklemeSaniye = 600

$script:AdimAdi = 'baslangic'
$script:GizliDegerler = @()   # hata mesajlarindan maskelenecek degerler (parola)

# ---------------------------------------------------------------------------------------------------
# Yardimcilar
# ---------------------------------------------------------------------------------------------------
function Write-TpLog([string] $Metin) {
    $satir = '{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'), $script:AdimAdi, $Metin
    try { Add-Content -Path (Join-Path $LogDizini 'kurulum.log') -Value $satir -Encoding UTF8 } catch { }
}

function Write-Seri([string] $Satir) {
    # stdout -> GCEMetadataScripts -> seri port 1 (bkz. ust aciklama)
    [Console]::Out.WriteLine($Satir)
    [Console]::Out.Flush()
    Write-TpLog $Satir
}

# Tani: bir log dosyasinin son satirlarini seri porta yazar (Get-TemizMesaj ile maskeli, ASCII).
# VM'e uzaktan giris yok; hata aninda tek gorunur kanal seri porttur.
function Write-LogKuyrugu([string] $Yol, [int] $Satir = 30) {
    $ad = Split-Path -Leaf $Yol
    if (-not (Test-Path $Yol)) { Write-Seri "TP-WINDOWS-LOG $ad (yok)"; return }
    try {
        foreach ($s in (Get-Content -Path $Yol -Tail $Satir -ErrorAction Stop)) {
            if ($s.Trim()) { Write-Seri ("TP-WINDOWS-LOG {0} {1}" -f $ad, (Get-TemizMesaj $s)) }
        }
    } catch { Write-Seri "TP-WINDOWS-LOG $ad (okunamadi)" }
}

function Get-TemizMesaj([string] $Mesaj) {
    foreach ($g in $script:GizliDegerler) {
        if ($g) { $Mesaj = $Mesaj.Replace($g, '***') }
    }
    $Mesaj = ($Mesaj -replace '\s+', ' ' -replace '[^\x20-\x7E]', '?').Trim()
    if ($Mesaj.Length -gt 300) { $Mesaj = $Mesaj.Substring(0, 300) + '...' }
    if (-not $Mesaj) { $Mesaj = 'bilinmeyen hata' }
    return $Mesaj
}

# Her adim bu sarmalayicidan gecer: hata olursa adim adiyla HATA satiri yazilir ve betik 1 ile biter.
function Invoke-Adim([string] $Ad, [scriptblock] $Is) {
    $script:AdimAdi = $Ad
    try {
        $sonuc = & $Is
        if ($sonuc -is [string] -and $sonuc) { Write-Seri "TP-WINDOWS-ADIM $Ad $sonuc" }
        else { Write-Seri "TP-WINDOWS-ADIM $Ad tamam" }
    } catch {
        Write-Seri ("TP-WINDOWS-HATA {0} {1}" -f $Ad, (Get-TemizMesaj $_.Exception.Message))
        exit 1
    }
}

function Get-Isaret([string] $Ad) {
    $yol = Join-Path $DurumDizini "$Ad.ok"
    if (Test-Path $yol) { return (Get-Content -Path $yol -Raw).Trim() }
    return $null
}

function Set-Isaret([string] $Ad, [string] $Anahtar) {
    Set-Content -Path (Join-Path $DurumDizini "$Ad.ok") -Value $Anahtar -Encoding ASCII
}

function Remove-Isaret([string] $Ad) {
    Remove-Item -Path (Join-Path $DurumDizini "$Ad.ok") -Force -ErrorAction SilentlyContinue
}

# Yerel komut calistirir; ciktiyi adim loguna yazar (seri portu doldurmaz). PS 5.1'de 2>&1 ile
# yonlendirilen stderr, ErrorActionPreference=Stop iken istisnaya donusur; bu yuzden gecici Continue.
function Invoke-Komut([string] $Dosya, [string[]] $Argumanlar, [string] $LogAdi, [int[]] $BasariliKodlar = @(0)) {
    $log = Join-Path $LogDizini "$LogAdi.log"
    Add-Content -Path $log -Value ("==> {0} {1}" -f (Get-Date -Format 'o'), $Dosya) -Encoding UTF8
    $onceki = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Dosya @Argumanlar 2>&1 | ForEach-Object { "$_" } | Add-Content -Path $log -Encoding UTF8
        $kod = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $onceki
    }
    if ($BasariliKodlar -notcontains $kod) {
        throw ("{0} cikis kodu {1} (ayrinti: {2})" -f (Split-Path -Leaf $Dosya), $kod, $log)
    }
}

function Get-Metadata([string] $Anahtar, [string] $Varsayilan) {
    $url = "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$Anahtar"
    try {
        $deger = Invoke-RestMethod -Uri $url -Headers @{ 'Metadata-Flavor' = 'Google' } -TimeoutSec 10 -UseBasicParsing
        $deger = "$deger".Trim()
        if ($deger) { return $deger }
    } catch {
        # 404 = anahtar tanimli degil -> varsayilan
    }
    return $Varsayilan
}

function Invoke-Indir([string] $Url, [string] $Hedef) {
    $gecici = "$Hedef.part"
    Remove-Item -Path $gecici -Force -ErrorAction SilentlyContinue
    for ($deneme = 1; $deneme -le 3; $deneme++) {
        try {
            Invoke-WebRequest -Uri $Url -OutFile $gecici -UseBasicParsing -TimeoutSec 600
            Move-Item -Path $gecici -Destination $Hedef -Force
            return
        } catch {
            if ($deneme -eq 3) { throw ("indirilemedi: {0} ({1})" -f $Url, $_.Exception.Message) }
            Start-Sleep -Seconds (5 * $deneme)
        }
    }
}

function Assert-Ozet([string] $Dosya, [string] $Algoritma, [string] $Beklenen) {
    $gercek = (Get-FileHash -Path $Dosya -Algorithm $Algoritma).Hash.ToLowerInvariant()
    if ($gercek -ne $Beklenen.ToLowerInvariant()) {
        Remove-Item -Path $Dosya -Force -ErrorAction SilentlyContinue
        throw ("{0} dogrulamasi basarisiz: {1}" -f $Algoritma, (Split-Path -Leaf $Dosya))
    }
}

function Get-MetinOzeti([string] $Metin) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $baytlar = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Metin))
        return ([System.BitConverter]::ToString($baytlar) -replace '-', '').ToLowerInvariant()
    } finally { $sha.Dispose() }
}

# Dizin icerigi ozeti (goreli yol + dosya SHA256); build/bin/obj haric.
function Get-DizinOzeti([string] $Dizin) {
    $tam = (Resolve-Path $Dizin).Path.TrimEnd('\')
    $satirlar = Get-ChildItem -Path $tam -Recurse -File |
        Where-Object { $_.FullName.Substring($tam.Length) -notmatch '\\(build|bin|obj)\\' } |
        Sort-Object FullName |
        ForEach-Object { '{0} {1}' -f $_.FullName.Substring($tam.Length), (Get-FileHash -Path $_.FullName -Algorithm SHA256).Hash }
    return Get-MetinOzeti ($satirlar -join "`n")
}

function Expand-Zip([string] $Zip, [string] $Hedef) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path $Hedef) { Remove-Item -Path $Hedef -Recurse -Force }
    [System.IO.Compression.ZipFile]::ExtractToDirectory($Zip, $Hedef)
}

# Bu betigin (SYSTEM) baslattigi degil, oturumdaki gorevin baslattigi Appium sureclerini durdurur
# (kurulum betigi elle yeniden kosturulursa npm ci / yayin dosya kilidine takilmasin).
function Stop-Appium {
    try { Stop-ScheduledTask -TaskName $GorevAdi -ErrorAction SilentlyContinue } catch { }
    Get-CimInstance -ClassName Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*\tp\appium\*' } |
        ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }
}

function Test-AppiumHazir {
    try {
        $yanit = Invoke-RestMethod -Uri "http://127.0.0.1:$AppiumPort/status" -TimeoutSec 5 -UseBasicParsing
        return [bool]$yanit.value.ready
    } catch { return $false }
}

# CSPRNG (RandomNumberGenerator) ile [0, N) araliginda tamsayi; modulo yanliligi olmadan (reddetme).
function Get-RastgeleIndeks($Rng, [int] $N) {
    $bayt = New-Object byte[] 4
    $aralik = [long]4294967296
    $sinir = $aralik - ($aralik % $N)
    do {
        $Rng.GetBytes($bayt)
        $deger = [long][System.BitConverter]::ToUInt32($bayt, 0)
    } while ($deger -ge $sinir)
    return [int]($deger % $N)
}

function New-RastgeleParola([int] $Uzunluk = 32) {
    $kumeler = @('ABCDEFGHJKLMNPQRSTUVWXYZ', 'abcdefghijkmnopqrstuvwxyz', '23456789', '!#%+-=?@_')
    $tumu = -join $kumeler
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        # Her karakter sinifindan en az bir tane (Windows karmasiklik ilkesi), kalanlar tum kumeden.
        $karakterler = New-Object System.Collections.Generic.List[char]
        foreach ($k in $kumeler) { $karakterler.Add($k[(Get-RastgeleIndeks $rng $k.Length)]) }
        while ($karakterler.Count -lt $Uzunluk) { $karakterler.Add($tumu[(Get-RastgeleIndeks $rng $tumu.Length)]) }
        # Fisher-Yates karistirma (yine CSPRNG ile)
        for ($i = $karakterler.Count - 1; $i -gt 0; $i--) {
            $j = Get-RastgeleIndeks $rng ($i + 1)
            $gecici = $karakterler[$i]; $karakterler[$i] = $karakterler[$j]; $karakterler[$j] = $gecici
        }
        return -join $karakterler
    } finally { $rng.Dispose() }
}

# Otomatik oturum parolasi LSA gizli verisi olarak saklanir ("DefaultPassword"; Sysinternals Autologon
# ile ayni yontem): Winlogon kayit defterinde DefaultPassword yoksa LSA'dan okur. Duz metin kayit
# defteri degerine (herkesin okuyabildigi Winlogon anahtari) ancak LSA cagrisi basarisiz olursa
# dusulur; bu durumda parola yonetici/SYSTEM'in okuyabildigi HKLM'de duz metindir (bilinen odun:
# yalnizca VM icinde, hesap yonetici degil ve VM disina ag erisimi yok).
$LsaKaynak = @'
using System;
using System.Runtime.InteropServices;
public static class TpLsa {
    [StructLayout(LayoutKind.Sequential)]
    private struct LSA_UNICODE_STRING { public ushort Length; public ushort MaximumLength; public IntPtr Buffer; }
    [StructLayout(LayoutKind.Sequential)]
    private struct LSA_OBJECT_ATTRIBUTES {
        public int Length; public IntPtr RootDirectory; public IntPtr ObjectName; public uint Attributes;
        public IntPtr SecurityDescriptor; public IntPtr SecurityQualityOfService;
    }
    [DllImport("advapi32.dll")]
    private static extern uint LsaOpenPolicy(IntPtr systemName, ref LSA_OBJECT_ATTRIBUTES attrs, uint access, out IntPtr handle);
    [DllImport("advapi32.dll")]
    private static extern uint LsaStorePrivateData(IntPtr handle, ref LSA_UNICODE_STRING key, ref LSA_UNICODE_STRING data);
    [DllImport("advapi32.dll")]
    private static extern uint LsaClose(IntPtr handle);
    [DllImport("advapi32.dll")]
    private static extern int LsaNtStatusToWinError(uint status);
    private const uint POLICY_ALL_ACCESS = 0x000F0FFF;

    private static LSA_UNICODE_STRING Olustur(string s) {
        LSA_UNICODE_STRING u = new LSA_UNICODE_STRING();
        u.Buffer = Marshal.StringToHGlobalUni(s);
        u.Length = (ushort)(s.Length * 2);
        u.MaximumLength = (ushort)(s.Length * 2 + 2);
        return u;
    }

    public static void Sakla(string anahtar, string deger) {
        LSA_OBJECT_ATTRIBUTES attrs = new LSA_OBJECT_ATTRIBUTES();
        attrs.Length = Marshal.SizeOf(typeof(LSA_OBJECT_ATTRIBUTES));
        IntPtr politika;
        uint durum = LsaOpenPolicy(IntPtr.Zero, ref attrs, POLICY_ALL_ACCESS, out politika);
        if (durum != 0) { throw new System.ComponentModel.Win32Exception(LsaNtStatusToWinError(durum)); }
        LSA_UNICODE_STRING k = Olustur(anahtar);
        LSA_UNICODE_STRING d = Olustur(deger);
        try {
            durum = LsaStorePrivateData(politika, ref k, ref d);
            if (durum != 0) { throw new System.ComponentModel.Win32Exception(LsaNtStatusToWinError(durum)); }
        } finally {
            Marshal.FreeHGlobal(k.Buffer);
            Marshal.ZeroFreeGlobalAllocUnicode(d.Buffer);
            LsaClose(politika);
        }
    }
}
'@

# ---------------------------------------------------------------------------------------------------
# Oturum betigi (tpotomasyon oturumunda zamanlanmis gorevle calisir). __YER_TUTUCU__ degerleri asagida
# doldurulur. Ekran: GCP ekran aygiti (Microsoft Basic Display Adapter) ozel surucusuz calisir;
# Set-DisplayResolution Server'da yok. ChangeDisplaySettings ile >= 1440x900 kip aranir (tercih tam
# 1440x900; ekran goruntusu kucuk kalsin). Kip listesi yetersizse sonuc ekran.txt'ye yazilir ve
# kurulum betigi HATA verir. Kip listesini genisletmek icin ilk kurulumda `bcdedit highestmode` acilir.
# ---------------------------------------------------------------------------------------------------
$OturumSablonu = @'
# tp-windows oturum betigi: kurulum.ps1 tarafindan uretilir, elle duzenlemeyin.
$ErrorActionPreference = 'Stop'
$log = '__LOG_DIZINI__\oturum.log'
function Yaz([string] $m) { Add-Content -Path $log -Value ('{0} {1}' -f (Get-Date -Format 'o'), $m) -Encoding UTF8 }

# Ekran koruyucu kapali (kullanici duzeyi), Server Manager oturum acilisinda acilmaz.
try {
    Set-ItemProperty -Path 'HKCU:\Control Panel\Desktop' -Name ScreenSaveActive -Value '0'
    Set-ItemProperty -Path 'HKCU:\Control Panel\Desktop' -Name ScreenSaverIsSecure -Value '0'
    Set-ItemProperty -Path 'HKCU:\Control Panel\Desktop' -Name ScreenSaveTimeOut -Value '0'
    New-Item -Path 'HKCU:\Software\Microsoft\ServerManager' -Force | Out-Null
    Set-ItemProperty -Path 'HKCU:\Software\Microsoft\ServerManager' -Name DoNotOpenServerManagerAtLogon -Value 1 -Type DWord
    Get-Process -Name ServerManager -ErrorAction SilentlyContinue | Stop-Process -Force
} catch { Yaz ("kullanici ayari: " + $_.Exception.Message) }

# Bu acilisin kurulum adimlari bitene kadar bekle (bayrak = acilis zamani).
$acilis = (Get-CimInstance -ClassName Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('yyyyMMddHHmmss')
$bitis = (Get-Date).AddMinutes(90)
while ($true) {
    $bayrak = $null
    if (Test-Path '__BASLAT_BAYRAGI__') { $bayrak = (Get-Content -Path '__BASLAT_BAYRAGI__' -Raw).Trim() }
    if ($bayrak -eq $acilis) { break }
    if ((Get-Date) -gt $bitis) { Yaz 'kurulum bayragi 90 dk icinde gelmedi; cikiliyor'; exit 1 }
    Start-Sleep -Seconds 5
}

# Ekran cozunurlugu
$ekranKaynak = @"
using System;
using System.Runtime.InteropServices;
public static class TpEkran {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct DEVMODE {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
        public short dmSpecVersion; public short dmDriverVersion; public short dmSize; public short dmDriverExtra;
        public int dmFields; public int dmPositionX; public int dmPositionY; public int dmDisplayOrientation;
        public int dmDisplayFixedOutput; public short dmColor; public short dmDuplex; public short dmYResolution;
        public short dmTTOption; public short dmCollate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
        public short dmLogPixels; public int dmBitsPerPel; public int dmPelsWidth; public int dmPelsHeight;
        public int dmDisplayFlags; public int dmDisplayFrequency; public int dmICMMethod; public int dmICMIntent;
        public int dmMediaType; public int dmDitherType; public int dmReserved1; public int dmReserved2;
        public int dmPanningWidth; public int dmPanningHeight;
    }
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern bool EnumDisplaySettings(string deviceName, int modeNum, ref DEVMODE devMode);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int ChangeDisplaySettings(ref DEVMODE devMode, int flags);
    const int ENUM_CURRENT_SETTINGS = -1;
    const int CDS_UPDATEREGISTRY = 0x01;
    const int DM_PELSWIDTH = 0x80000;
    const int DM_PELSHEIGHT = 0x100000;

    static DEVMODE Yeni() { DEVMODE d = new DEVMODE(); d.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE)); return d; }

    public static string Gecerli() {
        DEVMODE d = Yeni();
        if (!EnumDisplaySettings(null, ENUM_CURRENT_SETTINGS, ref d)) { return "0x0"; }
        return d.dmPelsWidth + "x" + d.dmPelsHeight;
    }

    // Tercih edilen kip varsa onu, yoksa en az minW x minH olan en kucuk kipi uygular.
    public static string Ayarla(int minW, int minH, int tercihW, int tercihH) {
        DEVMODE simdi = Yeni();
        if (!EnumDisplaySettings(null, ENUM_CURRENT_SETTINGS, ref simdi)) { return "gecerli kip okunamadi"; }
        if (simdi.dmPelsWidth == tercihW && simdi.dmPelsHeight == tercihH) { return "degismedi"; }
        DEVMODE secilen = Yeni(); bool bulundu = false; long enKucuk = long.MaxValue;
        DEVMODE m = Yeni();
        for (int i = 0; EnumDisplaySettings(null, i, ref m); i++) {
            if (m.dmBitsPerPel < 24) { m = Yeni(); continue; }
            if (m.dmPelsWidth == tercihW && m.dmPelsHeight == tercihH) { secilen = m; bulundu = true; break; }
            long alan = (long)m.dmPelsWidth * m.dmPelsHeight;
            if (m.dmPelsWidth >= minW && m.dmPelsHeight >= minH && alan < enKucuk) { secilen = m; enKucuk = alan; bulundu = true; }
            m = Yeni();
        }
        if (!bulundu) { return "uygun kip yok"; }
        if (simdi.dmPelsWidth >= minW && simdi.dmPelsHeight >= minH && !(secilen.dmPelsWidth == tercihW && secilen.dmPelsHeight == tercihH)) {
            return "degismedi";
        }
        secilen.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT;
        int r = ChangeDisplaySettings(ref secilen, CDS_UPDATEREGISTRY);
        return r == 0 ? "ayarlandi" : ("ChangeDisplaySettings=" + r);
    }
}
"@
try {
    Add-Type -TypeDefinition $ekranKaynak -Language CSharp
    $sonuc = [TpEkran]::Ayarla(__EKRAN_MIN_G__, __EKRAN_MIN_Y__, __EKRAN_MIN_G__, __EKRAN_MIN_Y__)
    Yaz ("ekran: $sonuc -> " + [TpEkran]::Gecerli())
    Set-Content -Path '__EKRAN_DOSYASI__' -Value ("$acilis " + [TpEkran]::Gecerli()) -Encoding ASCII
} catch {
    Yaz ("ekran hatasi: " + $_.Exception.Message)
    Set-Content -Path '__EKRAN_DOSYASI__' -Value "$acilis 0x0" -Encoding ASCII
}

# Appium (kilit dosyasindaki surum + NovaWindows). --relaxed-security YOK.
$env:APPIUM_HOME = '__APPIUM_HOME__'
$env:Path = '__NODE_DIZINI__;' + $env:Path
Yaz 'appium baslatiliyor'
& '__NODE_DIZINI__\node.exe' '__APPIUM_HOME__\node_modules\appium\index.js' `
    --address 0.0.0.0 --port __APPIUM_PORT__ --use-drivers novawindows `
    --log '__LOG_DIZINI__\appium.log' --log-no-colors --log-timestamp *> $null
Yaz ("appium cikti: kod $LASTEXITCODE")
exit 1
'@

# ===================================================================================================
# Akis
# ===================================================================================================
foreach ($d in @($Kok, $DurumDizini, $LogDizini, $OturumDizini, $IndirDizini, $AracDizini, $BetikDizini)) {
    New-Item -ItemType Directory -Path $d -Force | Out-Null
}

# --- metadata (BASLADI satiri icin once ref okunur) ---
$script:AdimAdi = 'metadata'
$Repo = Get-Metadata 'tp-repo' 'ThinkGOtr/testingprobe'
$Ref = Get-Metadata 'tp-repo-ref' 'dev'
$IzinliKaynak = Get-Metadata 'tp-izinli-kaynak' '10.156.0.2'
$ApiUrl = Get-Metadata 'tp-api-url' 'https://bayi.testing-probe.antreklabs.com/api'
$RefYazim = if ($Ref -match '^[A-Za-z0-9._/-]{1,100}$') { $Ref } else { 'gecersiz' }
Write-Seri "TP-WINDOWS-BASLADI ref=$RefYazim"

Invoke-Adim 'metadata' {
    if ($Repo -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw "tp-repo gecersiz: $Repo" }
    if ($Ref -notmatch '^[A-Za-z0-9._/-]{1,100}$' -or $Ref -match '\.\.') { throw 'tp-repo-ref gecersiz' }
    # vm.sh tek IPv4 garanti eder; burada da yalnizca tek, ozel olmayan-genis IPv4 kabul edilir
    # (CIDR, virgul, 0.0.0.0, Any vb. reddedilir: 4723 asla genis bir araliga acilmaz).
    $ip = $null
    if ($IzinliKaynak -notmatch '^\d{1,3}(\.\d{1,3}){3}$' -or -not [System.Net.IPAddress]::TryParse($IzinliKaynak, [ref]$ip)) {
        throw "tp-izinli-kaynak tek bir IPv4 olmali: $IzinliKaynak"
    }
    if ($IzinliKaynak -eq '0.0.0.0' -or $IzinliKaynak -eq '255.255.255.255') { throw "tp-izinli-kaynak gecersiz: $IzinliKaynak" }
    if ($ApiUrl -notmatch '^https?://[^\s''"]+$') { throw 'tp-api-url gecersiz (http/https, bosluk/tirnak yok)' }
    return "repo=$Repo ref=$Ref"
}

# --- kaynak: codeload zip (git yok). Commit degistiyse yeniden indirilir. ---
Invoke-Adim 'kaynak' {
    $sha = $null
    try {
        $commit = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/commits/$Ref" -UseBasicParsing -TimeoutSec 30 `
            -Headers @{ 'Accept' = 'application/vnd.github+json'; 'User-Agent' = 'tp-windows-kurulum' }
        if ("$($commit.sha)" -match '^[0-9a-f]{40}$') { $sha = "$($commit.sha)" }
    } catch {
        Write-TpLog ("GitHub API okunamadi, zip ozetine dusuluyor: " + (Get-TemizMesaj $_.Exception.Message))
    }
    $onceki = Get-Isaret 'kaynak'
    if ($sha -and $onceki -eq "$Repo@$sha" -and (Test-Path (Join-Path $KaynakDizini 'tools\appium\package-lock.json'))) {
        return 'atlandi'
    }
    $zip = Join-Path $IndirDizini 'kaynak.zip'
    if ($sha) { $url = "https://codeload.github.com/$Repo/zip/$sha" }
    else { $url = "https://codeload.github.com/$Repo/zip/refs/heads/$Ref" }
    Invoke-Indir $url $zip
    $anahtar = if ($sha) { "$Repo@$sha" } else { "$Repo@zip-" + (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLowerInvariant() }
    if ($onceki -eq $anahtar -and (Test-Path (Join-Path $KaynakDizini 'tools\appium\package-lock.json'))) {
        return 'atlandi'
    }
    # Yalnizca gereken alt agaclar cikarilir (kisa yol, hizli).
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $yeni = "$KaynakDizini.yeni"
    if (Test-Path $yeni) { Remove-Item -Path $yeni -Recurse -Force }
    $arsiv = [System.IO.Compression.ZipFile]::OpenRead($zip)
    try {
        $sayi = 0
        foreach ($e in $arsiv.Entries) {
            $parca = $e.FullName -split '/', 2
            if ($parca.Count -lt 2 -or -not $parca[1]) { continue }
            $goreli = $parca[1]
            if (-not ($goreli.StartsWith('tools/appium/') -or $goreli.StartsWith('demo-app/desktop/'))) { continue }
            if ($goreli.EndsWith('/') -or $goreli -match '(^|/)\.\.(/|$)') { continue }
            $hedef = Join-Path $yeni ($goreli -replace '/', '\')
            New-Item -ItemType Directory -Path (Split-Path -Parent $hedef) -Force | Out-Null
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, $hedef, $true)
            $sayi++
        }
    } finally { $arsiv.Dispose() }
    foreach ($gerekli in @('tools\appium\package.json', 'tools\appium\package-lock.json', 'demo-app\desktop\scripts\yayinla.ps1')) {
        if (-not (Test-Path (Join-Path $yeni $gerekli))) { throw "zip'te $gerekli yok (ref=$Ref)" }
    }
    if (Test-Path $KaynakDizini) { Remove-Item -Path $KaynakDizini -Recurse -Force }
    Move-Item -Path $yeni -Destination $KaynakDizini
    Remove-Item -Path $zip -Force -ErrorAction SilentlyContinue
    Set-Isaret 'kaynak' $anahtar
    return "guncellendi $sayi dosya"
}

# --- node (sabit surum, SHA256 dogrulamali zip) ---
Invoke-Adim 'node' {
    if ((Get-Isaret 'node') -eq $NodeSurum -and (Test-Path (Join-Path $NodeDizini 'node.exe'))) { return 'atlandi' }
    $zip = Join-Path $IndirDizini "node-v$NodeSurum-win-x64.zip"
    Invoke-Indir "https://nodejs.org/dist/v$NodeSurum/node-v$NodeSurum-win-x64.zip" $zip
    Assert-Ozet $zip 'SHA256' $NodeZipSha256
    Expand-Zip $zip "$NodeDizini.yeni"
    if (Test-Path $NodeDizini) { Remove-Item -Path $NodeDizini -Recurse -Force }
    Move-Item -Path (Join-Path "$NodeDizini.yeni" "node-v$NodeSurum-win-x64") -Destination $NodeDizini
    Remove-Item -Path "$NodeDizini.yeni" -Recurse -Force
    Remove-Item -Path $zip -Force
    Set-Isaret 'node' $NodeSurum
}
$env:Path = "$NodeDizini;$env:Path"

# --- appium: tools/appium kilit dosyasiyla npm ci (APPIUM_HOME=C:\tp\appium) + NovaWindows ---
Invoke-Adim 'appium' {
    $kilitOzeti = (Get-FileHash -Path (Join-Path $KaynakDizini 'tools\appium\package-lock.json') -Algorithm SHA256).Hash.ToLowerInvariant()
    $anahtar = "node=$NodeSurum kilit=$kilitOzeti novawindows=$NovaWindowsSurum"
    $appiumJs = Join-Path $AppiumHome 'node_modules\appium\index.js'
    if ((Get-Isaret 'appium') -eq $anahtar -and (Test-Path $appiumJs)) { return 'atlandi' }
    Remove-Isaret 'appium'
    Stop-Appium
    if (Test-Path $AppiumHome) { Remove-Item -Path $AppiumHome -Recurse -Force }
    New-Item -ItemType Directory -Path $AppiumHome -Force | Out-Null
    Copy-Item -Path (Join-Path $KaynakDizini 'tools\appium\package.json') -Destination $AppiumHome
    Copy-Item -Path (Join-Path $KaynakDizini 'tools\appium\package-lock.json') -Destination $AppiumHome
    $env:APPIUM_HOME = $AppiumHome
    $env:npm_config_cache = Join-Path $Kok 'npm-onbellek'
    $env:npm_config_update_notifier = 'false'
    $npm = Join-Path $NodeDizini 'npm.cmd'
    Push-Location $AppiumHome
    try {
        Invoke-Komut $npm @('ci', '--no-audit', '--no-fund', '--loglevel=error') 'npm-ci'
        Invoke-Komut (Join-Path $NodeDizini 'node.exe') @($appiumJs, 'driver', 'install', '--source=npm', "appium-novawindows-driver@$NovaWindowsSurum") 'appium-surucu'
        Invoke-Komut (Join-Path $NodeDizini 'node.exe') @($appiumJs, 'driver', 'list', '--installed') 'appium-surucu'
    } finally { Pop-Location }
    $surucu = Join-Path $AppiumHome 'node_modules\appium-novawindows-driver\package.json'
    if (-not (Test-Path $surucu)) { throw 'NovaWindows surucusu kurulmadi' }
    $kurulan = (Get-Content -Path $surucu -Raw | ConvertFrom-Json).version
    if ($kurulan -ne $NovaWindowsSurum) { throw "NovaWindows surumu $kurulan (beklenen $NovaWindowsSurum)" }
    # Appium acilista APPIUM_HOME'daki eklenti onbellegini yazabilir; oturum kullanicisina yalnizca
    # bu dizinde yazma izni verilir (kod dizinleri SYSTEM'e ait kalir).
    $onbellek = Join-Path $AppiumHome 'node_modules\.cache'
    New-Item -ItemType Directory -Path $onbellek -Force | Out-Null
    Set-Isaret 'appium' $anahtar
}

# --- dotnet SDK (sabit surum, SHA512 dogrulamali resmi zip) ---
Invoke-Adim 'dotnet' {
    if ((Get-Isaret 'dotnet') -eq $DotnetSdkSurum -and (Test-Path (Join-Path $DotnetDizini 'dotnet.exe'))) { return 'atlandi' }
    $zip = Join-Path $IndirDizini "dotnet-sdk-$DotnetSdkSurum-win-x64.zip"
    Invoke-Indir "https://builds.dotnet.microsoft.com/dotnet/Sdk/$DotnetSdkSurum/dotnet-sdk-$DotnetSdkSurum-win-x64.zip" $zip
    Assert-Ozet $zip 'SHA512' $DotnetSdkZipSha512
    Expand-Zip $zip "$DotnetDizini.yeni"
    if (Test-Path $DotnetDizini) { Remove-Item -Path $DotnetDizini -Recurse -Force }
    Move-Item -Path "$DotnetDizini.yeni" -Destination $DotnetDizini
    Remove-Item -Path $zip -Force
    Set-Isaret 'dotnet' $DotnetSdkSurum
}

# --- uygulama: demo-app/desktop/scripts/yayinla.ps1 -Rid win-x64 (self-contained) -> C:\tp\uygulama ---
Invoke-Adim 'uygulama' {
    $masaustu = Join-Path $KaynakDizini 'demo-app\desktop'
    $anahtar = "sdk=$DotnetSdkSurum kaynak=" + (Get-DizinOzeti $masaustu)
    if ((Get-Isaret 'uygulama') -eq $anahtar -and (Test-Path $UygulamaExe)) { return 'atlandi' }
    Remove-Isaret 'uygulama'
    $env:DOTNET_ROOT = $DotnetDizini
    $env:Path = "$DotnetDizini;$env:Path"
    $env:DOTNET_CLI_HOME = Join-Path $Kok 'dotnet-ev'
    $env:NUGET_PACKAGES = Join-Path $Kok 'nuget'
    $env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
    $env:DOTNET_NOLOGO = '1'
    $env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
    $env:DOTNET_MULTILEVEL_LOOKUP = '0'
    # yayinla.ps1 ayri powershell surecinde: kendi throw/ErrorActionPreference'i bu betigi etkilemesin.
    Invoke-Komut "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', (Join-Path $masaustu 'scripts\yayinla.ps1'), '-Rid', 'win-x64') 'uygulama-yayin'
    $cikti = Join-Path $masaustu 'build\win-x64'
    if (-not (Test-Path (Join-Path $cikti 'BayiSiparis.exe'))) { throw "BayiSiparis.exe uretilmedi: $cikti" }
    Stop-Appium
    Get-Process -Name BayiSiparis -ErrorAction SilentlyContinue | Stop-Process -Force
    New-Item -ItemType Directory -Path $UygulamaDizini -Force | Out-Null
    # robocopy: 0-7 basari, >=8 hata
    Invoke-Komut "$env:WINDIR\System32\robocopy.exe" @($cikti, $UygulamaDizini, '/MIR', '/NP', '/NFL', '/NDL', '/R:2', '/W:2') 'uygulama-kopya' @(0, 1, 2, 3, 4, 5, 6, 7)
    if (-not (Test-Path $UygulamaExe)) { throw "uygulama yok: $UygulamaExe" }
    Set-Isaret 'uygulama' $anahtar
}

# --- kullanici + otomatik oturum ---
Invoke-Adim 'kullanici' {
    $mevcut = Get-LocalUser -Name $Kullanici -ErrorAction SilentlyContinue
    $winlogon = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
    $durum = 'atlandi'
    if (-not $mevcut -or -not (Get-Isaret 'kullanici')) {
        # Parola yalnizca bellekte; dosyaya/loga yazilmaz. Yarim kalmis kurulumda yeniden uretilir.
        $parola = New-RastgeleParola 32
        $script:GizliDegerler = @($parola)
        $guvenli = ConvertTo-SecureString -String $parola -AsPlainText -Force
        if ($mevcut) {
            Set-LocalUser -Name $Kullanici -Password $guvenli -PasswordNeverExpires $true
            Enable-LocalUser -Name $Kullanici
        } else {
            New-LocalUser -Name $Kullanici -Password $guvenli -PasswordNeverExpires -AccountNeverExpires `
                -UserMayNotChangePassword -FullName 'TP otomasyon' -Description 'Appium/NovaWindows oturumu (kurulum.ps1)' | Out-Null
        }
        # Users grubu (SID ile; yerellestirilmis grup adindan bagimsiz). Yonetici DEGIL.
        try { Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $Kullanici }
        catch [Microsoft.PowerShell.Commands.MemberExistsException] { }
        $yontem = 'lsa'
        try {
            if (-not ('TpLsa' -as [type])) { Add-Type -TypeDefinition $LsaKaynak -Language CSharp }
            [TpLsa]::Sakla('DefaultPassword', $parola)
            Remove-ItemProperty -Path $winlogon -Name DefaultPassword -ErrorAction SilentlyContinue
        } catch {
            # Bkz. $LsaKaynak ustundeki not: duz metin kayit defteri yedegi.
            Write-TpLog ('LSA saklama basarisiz, Winlogon DefaultPassword kullaniliyor: ' + (Get-TemizMesaj $_.Exception.Message))
            Set-ItemProperty -Path $winlogon -Name DefaultPassword -Value $parola -Type String
            $yontem = 'kayit'
        }
        $parola = $null; $guvenli = $null
        Set-Isaret 'kullanici' $yontem
        $durum = "olusturuldu ($yontem)"
    }
    # Her acilista (ucuz): otomatik oturum degerleri yerinde mi
    Set-ItemProperty -Path $winlogon -Name AutoAdminLogon -Value '1' -Type String
    Set-ItemProperty -Path $winlogon -Name DefaultUserName -Value $Kullanici -Type String
    Set-ItemProperty -Path $winlogon -Name DefaultDomainName -Value $env:COMPUTERNAME -Type String
    Remove-ItemProperty -Path $winlogon -Name AutoLogonCount -ErrorAction SilentlyContinue
    return $durum
}

# --- oturum ayarlari: kilit ekrani, uyku, ekran zaman asimi, Server Manager, yasal uyari ---
Invoke-Adim 'oturum-ayarlari' {
    function Set-Kayit([string] $Yol, [string] $Ad, $Deger, [string] $Tur = 'DWord') {
        if (-not (Test-Path $Yol)) { New-Item -Path $Yol -Force | Out-Null }
        Set-ItemProperty -Path $Yol -Name $Ad -Value $Deger -Type $Tur
    }
    $sistem = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
    Set-Kayit 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization' 'NoLockScreen' 1
    Set-Kayit $sistem 'DisableCAD' 1
    Set-Kayit $sistem 'InactivityTimeoutSecs' 0
    Set-Kayit $sistem 'EnableFirstLogonAnimation' 0
    # Yasal uyari metni varsa otomatik oturum acma o pencerede durur.
    Set-Kayit $sistem 'LegalNoticeCaption' '' 'String'
    Set-Kayit $sistem 'LegalNoticeText' '' 'String'
    Set-Kayit 'HKLM:\SOFTWARE\Microsoft\ServerManager' 'DoNotOpenServerManagerAtLogon' 1
    Set-Kayit 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Server\ServerManager' 'DoNotOpenAtLogon' 1
    Get-ScheduledTask -TaskPath '\Microsoft\Windows\Server Manager\' -TaskName 'ServerManager' -ErrorAction SilentlyContinue |
        Disable-ScheduledTask -ErrorAction SilentlyContinue | Out-Null
    # Windows Update oturum acikken kendiliginden yeniden baslatmasin.
    Set-Kayit 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU' 'NoAutoRebootWithLoggedOnUsers' 1
    Set-Kayit 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' 'LongPathsEnabled' 1
    foreach ($a in @('monitor-timeout-ac', 'monitor-timeout-dc', 'standby-timeout-ac', 'standby-timeout-dc', 'hibernate-timeout-ac', 'hibernate-timeout-dc')) {
        Invoke-Komut "$env:WINDIR\System32\powercfg.exe" @('/change', $a, '0') 'powercfg'
    }
    Invoke-Komut "$env:WINDIR\System32\powercfg.exe" @('/hibernate', 'off') 'powercfg'
    Invoke-Komut "$env:WINDIR\System32\powercfg.exe" @('/setacvalueindex', 'SCHEME_CURRENT', 'SUB_NONE', 'CONSOLELOCK', '0') 'powercfg'
    # Ekran: UEFI'de Basic Display surucusu yalnizca onyukleyicinin GOP kipini kullanabilir;
    # highestmode, onyukleyiciyi en yuksek GOP kipine zorlar (ilk kurulumdaki yeniden baslatmada etkin).
    if (-not (Get-Isaret 'ekran-bcd')) {
        Invoke-Komut "$env:WINDIR\System32\bcdedit.exe" @('/set', '{current}', 'highestmode', 'on') 'bcdedit'
        Set-Isaret 'ekran-bcd' 'highestmode'
    }
    # API adresi (uygulama BAYI_API_URL'yi okur) - makine ortami
    [Environment]::SetEnvironmentVariable('BAYI_API_URL', $ApiUrl, 'Machine')
    [Environment]::SetEnvironmentVariable('APPIUM_HOME', $AppiumHome, 'Machine')
}

# --- guvenlik duvari: 4723 gelen yalnizca tp-izinli-kaynak'tan ---
Invoke-Adim 'guvenlik-duvari' {
    # "Erisime izin ver" bildirimi kapali: node.exe icin kendiliginden program kurali olusmasin.
    Set-NetFirewallProfile -Profile Domain, Private, Public -NotifyOnListen False
    # 4723'u acan baska tum gelen kurallar ve node.exe program kurallari kaldirilir.
    Get-NetFirewallPortFilter -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Protocol -eq 'TCP' -and @($_.LocalPort) -contains "$AppiumPort" } |
        Get-NetFirewallRule -ErrorAction SilentlyContinue |
        Where-Object { $_.Direction -eq 'Inbound' -and $_.Name -ne $KuralAdi } |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
    Get-NetFirewallApplicationFilter -Program '*node.exe' -ErrorAction SilentlyContinue |
        Get-NetFirewallRule -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
    Remove-NetFirewallRule -Name $KuralAdi -ErrorAction SilentlyContinue
    New-NetFirewallRule -Name $KuralAdi -DisplayName 'TP Appium 4723 (yalniz tp-izinli-kaynak)' `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort $AppiumPort `
        -RemoteAddress $IzinliKaynak -Profile Any | Out-Null
    return "izinli=$IzinliKaynak"
}

# --- gorev: tpotomasyon oturum acinca oturum.ps1 (Appium) ---
Invoke-Adim 'gorev' {
    $yerler = [ordered]@{
        '__LOG_DIZINI__'      = $LogDizini
        '__BASLAT_BAYRAGI__'  = $BaslatBayragi
        '__EKRAN_DOSYASI__'   = $EkranDosyasi
        '__EKRAN_MIN_G__'     = "$EkranMinGenislik"
        '__EKRAN_MIN_Y__'     = "$EkranMinYukseklik"
        '__APPIUM_HOME__'     = $AppiumHome
        '__NODE_DIZINI__'     = $NodeDizini
        '__APPIUM_PORT__'     = "$AppiumPort"
    }
    $icerik = $OturumSablonu
    foreach ($k in $yerler.Keys) { $icerik = $icerik.Replace($k, $yerler[$k]) }
    if ($icerik -match '__[A-Z_]+__') { throw "oturum betiginde doldurulmamis yer tutucu: $($Matches[0])" }
    Set-Content -Path $OturumBetigi -Value $icerik -Encoding ASCII
    # Izinler: kullanici log/oturum/onbellek dizinlerine yazar; betik ve kod dizinleri salt okunur.
    $hesap = "$env:COMPUTERNAME\$Kullanici"
    foreach ($d in @($LogDizini, $OturumDizini, (Join-Path $AppiumHome 'node_modules\.cache'))) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
        Invoke-Komut "$env:WINDIR\System32\icacls.exe" @($d, '/grant', "${hesap}:(OI)(CI)M", '/Q') 'icacls'
    }
    $eylem = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$OturumBetigi`""
    $tetik = New-ScheduledTaskTrigger -AtLogOn -User $hesap
    # Interactive: Appium kullanicinin masaustunde (UI Automation icin sart); yonetici yetkisi gerekmez.
    $sorumlu = New-ScheduledTaskPrincipal -UserId $hesap -LogonType Interactive -RunLevel Limited
    $ayar = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $GorevAdi -Action $eylem -Trigger $tetik -Principal $sorumlu -Settings $ayar -Force | Out-Null
}

# --- ilk kurulumda bir kez yeniden baslatma (otomatik oturum + highestmode etkinlessin) ---
# Isaret dosyasi yeniden baslatmadan ONCE yazilir: dongu olmaz.
if (-not (Get-Isaret 'yeniden-baslatma')) {
    $script:AdimAdi = 'yeniden-baslatma'
    Set-Isaret 'yeniden-baslatma' (Get-Date -Format 'o')
    Write-Seri 'TP-WINDOWS-ADIM yeniden-baslatma ilk-kurulum'
    Restart-Computer -Force
    exit 0
}

# --- baslat bayragi: oturum betigi bu acilisin kurulumunun bittigini buradan anlar ---
$acilisKimligi = (Get-CimInstance -ClassName Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('yyyyMMddHHmmss')
Invoke-Adim 'baslat-bayragi' {
    Remove-Item -Path $EkranDosyasi -Force -ErrorAction SilentlyContinue
    Set-Content -Path $BaslatBayragi -Value $acilisKimligi -Encoding ASCII
    # Betik elle yeniden kosturulduysa ve oturum zaten aciksa gorevi yeniden tetikle.
    if (-not (Test-AppiumHazir)) {
        try { Start-ScheduledTask -TaskName $GorevAdi -ErrorAction SilentlyContinue } catch { }
    }
}

# --- Appium'un oturumda ayaga kalkmasini bekle ---
Invoke-Adim 'appium-bekle' {
    $bitis = (Get-Date).AddSeconds($AppiumBeklemeSaniye)
    $oturumLog = Join-Path $LogDizini 'oturum.log'
    $appiumLog = Join-Path $LogDizini 'appium.log'
    $bayrakZamani = (Get-Item $BaslatBayragi).LastWriteTime
    while (-not (Test-AppiumHazir)) {
        # Appium bu acilista cikmissa (oturum betigi "appium cikti" yazar) 10 dk beklemeden bildir.
        $cikti = (Test-Path $oturumLog) -and ((Get-Item $oturumLog).LastWriteTime -gt $bayrakZamani) -and
            (Select-String -Path $oturumLog -Pattern 'appium cikti' -SimpleMatch -Quiet) -and
            ((Get-Content $oturumLog -Tail 1) -match 'appium cikti')
        if ($cikti -or ((Get-Date) -gt $bitis)) {
            Write-LogKuyrugu $oturumLog 15
            Write-LogKuyrugu $appiumLog 40
        }
        if ($cikti) { throw "Appium oturumda cikti (bkz. TP-WINDOWS-LOG satirlari)" }
        if ((Get-Date) -gt $bitis) {
            $oturum = Get-Process -Name explorer -IncludeUserName -ErrorAction SilentlyContinue |
                Where-Object { $_.UserName -like "*\$Kullanici" }
            if (-not $oturum) { throw "$Kullanici oturumu acik degil (otomatik oturum acma basarisiz?)" }
            throw "Appium $AppiumBeklemeSaniye sn icinde hazir olmadi (bkz. $LogDizini\appium.log, oturum.log)"
        }
        Start-Sleep -Seconds 5
    }
    # Bildirim kapali olsa da node.exe icin kural olustuysa kaldir (izin kurali tum portlari acar).
    Get-NetFirewallApplicationFilter -Program '*node.exe' -ErrorAction SilentlyContinue |
        Get-NetFirewallRule -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
}

# --- ekran cozunurlugu (oturum betiginin yazdigi sonuc) >= 1440x900 ---
Invoke-Adim 'ekran' {
    $bitis = (Get-Date).AddSeconds(60)
    while (-not (Test-Path $EkranDosyasi)) {
        if ((Get-Date) -gt $bitis) { throw 'ekran.txt yazilmadi (oturum betigi)' }
        Start-Sleep -Seconds 2
    }
    $parca = (Get-Content -Path $EkranDosyasi -Raw).Trim() -split ' '
    if ($parca[0] -ne $acilisKimligi -or $parca.Count -lt 2) { throw 'ekran.txt bu acilisa ait degil' }
    $wh = $parca[1] -split 'x'
    if ([int]$wh[0] -lt $EkranMinGenislik -or [int]$wh[1] -lt $EkranMinYukseklik) {
        throw ("cozunurluk {0} < {1}x{2} (bkz. {3}\oturum.log)" -f $parca[1], $EkranMinGenislik, $EkranMinYukseklik, $LogDizini)
    }
    return $parca[1]
}

Write-Seri "TP-WINDOWS-HAZIR appium=$AppiumPort uygulama=$UygulamaExe ref=$Ref"
exit 0
