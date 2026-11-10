# Bayi Sipariş Portalı (WPF) yayın betiği — Windows PowerShell 5.1 / PowerShell 7.
# Çıktı: demo-app\desktop\build\<rid>\BayiSiparis.exe (+ bağımlılıklar; tek klasör).
#
# Kullanım:
#   .\scripts\yayinla.ps1                          # win-x64 ve win-arm64, kendi içinde (self-contained)
#   .\scripts\yayinla.ps1 -Rid win-arm64           # yalnız ARM64 (Windows 11 ARM sanal makinesi)
#   .\scripts\yayinla.ps1 -CatiyaBagimli           # hedefte .NET 8 Desktop Runtime gerekir
#   .\scripts\yayinla.ps1 -Test                    # önce çekirdek testlerini koşturur
[CmdletBinding()]
param(
    [ValidateSet('win-x64', 'win-arm64')]
    [string[]] $Rid = @('win-x64', 'win-arm64'),
    [switch] $CatiyaBagimli,
    [switch] $Test
)

$ErrorActionPreference = 'Stop'
$kok = Split-Path -Parent $PSScriptRoot
$proje = Join-Path $kok 'src\BayiSiparis.Masaustu\BayiSiparis.Masaustu.csproj'
$cikti = Join-Path $kok 'build'
$kendiIcinde = if ($CatiyaBagimli) { 'false' } else { 'true' }
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_NOLOGO = '1'

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw 'dotnet bulunamadı (.NET SDK 8 veya üstü gerekir)'
}

if ($Test) {
    dotnet test (Join-Path $kok 'BayiSiparis.sln') -c Release
    if ($LASTEXITCODE -ne 0) { throw 'Testler başarısız' }
}

foreach ($r in $Rid) {
    $hedef = Join-Path $cikti $r
    Write-Host "==> $r (self-contained=$kendiIcinde) -> $hedef"
    if (Test-Path $hedef) { Remove-Item -Recurse -Force $hedef }
    dotnet publish $proje -c Release -r $r --self-contained $kendiIcinde -o $hedef -p:DebugType=none
    if ($LASTEXITCODE -ne 0) { throw "Yayın başarısız: $r" }
    if (-not (Test-Path (Join-Path $hedef 'BayiSiparis.exe'))) { throw "BayiSiparis.exe üretilmedi: $hedef" }
}

Write-Host 'Tamam:'
foreach ($r in $Rid) { Write-Host "  $(Join-Path (Join-Path $cikti $r) 'BayiSiparis.exe')" }
