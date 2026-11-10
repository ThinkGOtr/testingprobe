# test_windows_vm_kurulum_betigi.py yardimcisi: kurulum.ps1'i PowerShell ayristiricisiyla denetler,
# gomulu oturum betigini ayristirir, gomulu C# (LSA / ekran) kodunu derler, parola ureticisini sinar.
param([string] $Yol)
$ErrorActionPreference = 'Stop'
$t = $null; $e = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Yol, [ref]$t, [ref]$e)
if ($e.Count) { $e | ForEach-Object { Write-Output ("HATA kurulum: " + $_.ToString()) }; exit 1 }
$atamalar = $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.AssignmentStatementAst] }, $false)
function Deger($ad) { ($atamalar | Where-Object { $_.Left.Extent.Text -eq $ad } | Select-Object -First 1).Right.Expression.Value }
Add-Type -TypeDefinition (Deger '$LsaKaynak') -Language CSharp
$oturum = (Deger '$OturumSablonu').Replace('__EKRAN_MIN_G__', '1440').Replace('__EKRAN_MIN_Y__', '900').Replace('__APPIUM_PORT__', '4723')
$oturum = $oturum -replace '__[A-Z_]+__', 'C:\tp\x'
$ast2 = [System.Management.Automation.Language.Parser]::ParseInput($oturum, [ref]$t, [ref]$e)
if ($e.Count) { $e | ForEach-Object { Write-Output ("HATA oturum: " + $_.ToString()) }; exit 1 }
$a2 = $ast2.FindAll({ $args[0] -is [System.Management.Automation.Language.AssignmentStatementAst] }, $false)
Add-Type -TypeDefinition (($a2 | Where-Object { $_.Left.Extent.Text -eq '$ekranKaynak' }).Right.Expression.Value) -Language CSharp
$boyut = [Runtime.InteropServices.Marshal]::SizeOf([type]'TpEkran+DEVMODE')
if ($boyut -ne 220) { Write-Output "HATA DEVMODE boyutu $boyut (220 olmali)"; exit 1 }
$fns = $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $args[0].Name -in 'Get-RastgeleIndeks', 'New-RastgeleParola', 'Get-TemizMesaj' }, $true)
foreach ($fn in $fns) { . ([scriptblock]::Create($fn.Extent.Text)) }
$p1 = New-RastgeleParola 32; $p2 = New-RastgeleParola 32
$siniflar = ($p1 -cmatch '[A-Z]') -and ($p1 -cmatch '[a-z]') -and ($p1 -match '\d') -and ($p1 -match '[^A-Za-z0-9]')
if ($p1.Length -ne 32 -or $p1 -eq $p2 -or -not $siniflar) { Write-Output 'HATA parola uretimi'; exit 1 }
$script:GizliDegerler = @($p1)
$m = Get-TemizMesaj ("x " + $p1 + "`r`n y")
if ($m.Contains($p1) -or $m -ne 'x *** y') { Write-Output "HATA maskeleme: $m"; exit 1 }
Write-Output 'TAMAM'
