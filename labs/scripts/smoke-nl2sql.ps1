<#
.SYNOPSIS
  案例二 NL2SQL 问数 · 5 分钟自检脚本（HANDOFF §4.1 逐字实现）
.DESCRIPTION
  前置：cd cases\02-nl2sql; python -m src.server（监听 4181）
  四步断言：
    S1  python -m scripts.gen_db; python -m scripts.verify_db
        -> 11 行 [PASS]，输出含 "合计 8584"
    S2  GET /api/health          -> .tables 长度 = 6
    S3  三问（逐字）             -> 结果首行首列 = 541252.34 / 57 / 35
    S4  "帮我删掉2026年1月的账单" -> rejected.gate = write_intent
  输出：每步 [PASS]/[FAIL]，末尾 RESULT；全过 exit 0，否则 exit 1。
  注意：S1 会重建 data/aicoding.db 并覆写 data/manifest.json（HANDOFF §4.2 允许，事后须与 frozen-manifest 比对）。
#>
[CmdletBinding()]
param(
    [int]$Port = 4181,
    [int]$TimeoutSec = 300,
    [string]$ProjectDir = ''
)

# PS 5.1 下 $PSScriptRoot 在 param 默认值求值时为空，故在 param 之后解析项目目录
if (-not $ProjectDir) {
    $ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..\cases\02-nl2sql')).Path
}
$ErrorActionPreference = 'Stop'
# PS 5.1 默认不加载 System.Net.Http（PS 7 免加载）
try { Add-Type -AssemblyName System.Net.Http -ErrorAction Stop } catch { }
$script:passed = 0
$script:failed = 0
$base = "http://127.0.0.1:$Port"

function Write-Step([string]$id, [string]$text) { Write-Host ""; Write-Host "== $id $text ==" }
function Assert-That([string]$id, [string]$assertion, [bool]$ok, [string]$detail) {
    if ($ok) { $script:passed++; Write-Host ("[PASS] {0} {1} | {2}" -f $id, $assertion, $detail) }
    else     { $script:failed++; Write-Host ("[FAIL] {0} {1} | {2}" -f $id, $assertion, $detail) }
}
function Get-Snippet([string]$text, [int]$n = 160) {
    $flat = ($text -replace '\s+', ' ').Trim()
    if ($flat.Length -le $n) { return $flat }
    return $flat.Substring(0, $n) + '…'
}
# 统一走 HttpClient + 显式 UTF-8 解码：Windows PowerShell 5.1 的 Invoke-RestMethod 会按
# ISO-8859-1 解无 charset 的 JSON，中文会变乱码（影响 sql/columns 与取样片段）。
function Invoke-Json([string]$Path, [hashtable]$Payload, [int]$Timeout) {
    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromSeconds($Timeout)
    try {
        if ($null -eq $Payload) {
            $resp = $client.GetAsync("$base$Path").GetAwaiter().GetResult()
        } else {
            $json = $Payload | ConvertTo-Json -Compress -Depth 6
            $content = [System.Net.Http.StringContent]::new($json, [System.Text.Encoding]::UTF8, 'application/json')
            $resp = $client.PostAsync("$base$Path", $content).GetAwaiter().GetResult()
        }
        $bytes = $resp.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
        $code = [int]$resp.StatusCode
    } finally {
        $client.Dispose()
    }
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    if ($code -lt 200 -or $code -ge 300) { throw "HTTP $code $Path -> $text" }
    return $text | ConvertFrom-Json
}

function Invoke-Ask([string]$Question) {
    return Invoke-Json '/api/ask' @{ question = $Question; clarify = $true } $TimeoutSec
}
function Test-NumEqual($actual, $expected, [double]$tol) {
    if ($null -eq $actual) { return $false }
    $s = ([string]$actual) -replace ',', ''
    try { $d = [double]::Parse($s, [System.Globalization.CultureInfo]::InvariantCulture) }
    catch { return $false }
    return ([Math]::Abs($d - [double]$expected) -le $tol)
}

Write-Host "SMOKE-NL2SQL  base=$base  project=$ProjectDir  time=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

# ---------- S0 可达性（不计入断言） ----------
try {
    $health = Invoke-Json '/api/health' $null 15
} catch {
    Write-Host "[FAIL] S0 服务不可达：$base/api/health -> $($_.Exception.Message)"
    Write-Host "RESULT: FAIL (0/0) — 先启动服务：cd cases\02-nl2sql; python -m src.server"
    exit 1
}

# ---------- S1 重建 + 11 项断言 ----------
Write-Step 'S1' 'python -m scripts.gen_db; python -m scripts.verify_db'
$env:PYTHONIOENCODING = 'utf-8'
$oldEnc = [Console]::OutputEncoding
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
Push-Location $ProjectDir
# 原生命令的 stderr 在 $ErrorActionPreference='Stop' 下会被当成终止错误抛出，
# 这里局部放宽为 Continue，让 S1 的失败被"记录"而不是"中断"，便于继续取证 S2–S4。
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    $genOut = (& python -m scripts.gen_db 2>&1 | Out-String)
    $genCode = $LASTEXITCODE
    $verOut = (& python -m scripts.verify_db 2>&1 | Out-String)
    $verCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $prevEap
    Pop-Location
    try { [Console]::OutputEncoding = $oldEnc } catch { }
}
if ($null -eq $verOut) { $verOut = '' }
if ($null -eq $genOut) { $genOut = '' }
Write-Host "  gen_db exit=$genCode"
Write-Host "  $(Get-Snippet $genOut 200)"
Write-Host "  verify_db exit=$verCode"
foreach ($line in ($verOut -split "`n")) { if ($line.Trim()) { Write-Host "  $($line.TrimEnd())" } }

$passLines = ($verOut -split "`n" | Where-Object { $_ -match '^\[PASS\]' }).Count
Assert-That 'S1a' 'gen_db 退出码 = 0' ($genCode -eq 0) "exit=$genCode"
Assert-That 'S1b' 'verify_db 输出 11 行 [PASS]' ($passLines -eq 11) "got=$passLines"
Assert-That 'S1c' '输出含 "合计 8584"' ($verOut -match '合计\s*8584') "match=$($verOut -match '合计\s*8584')"
Assert-That 'S1d' 'verify_db 退出码 = 0' ($verCode -eq 0) "exit=$verCode"

# ---------- S2 health 表数 ----------
Write-Step 'S2' 'GET /api/health'
$tables = @($health.tables)
Write-Host "  tables=$($tables -join ',')"
Assert-That 'S2a' '.tables 长度 == 6' ($tables.Count -eq 6) "got=$($tables.Count)"

# ---------- S3 三个已知值 ----------
$cases = @(
    @{ id = 'S3a'; q = '2026年9月的应收合计是多少元？';        expect = 541252.34; tol = 0.005 },
    @{ id = 'S3b'; q = '杭州有多少家状态正常的客户？';          expect = 57;       tol = 0.0001 },
    @{ id = 'S3c'; q = '2026年9月故障工单里高优的有多少张？';    expect = 35;       tol = 0.0001 }
)
foreach ($c in $cases) {
    Write-Step $c.id "POST /api/ask  $($c.q)"
    $r = Invoke-Ask $c.q
    $first = $null
    if ($r.rows -and $r.rows.Count -gt 0 -and $r.rows[0].Count -gt 0) { $first = $r.rows[0][0] }
    Write-Host "  sql=$($r.sql)"
    Write-Host "  columns=$(($r.columns -join ','))  row_count=$($r.row_count)  first=$first  metrics_used=$(($r.metrics_used -join ','))"
    Assert-That $c.id "首行首列 == $($c.expect)" (Test-NumEqual $first $c.expect $c.tol) "got=$first"
}

# ---------- S4 写操作被拒 ----------
$q4 = '帮我删掉2026年1月的账单'
Write-Step 'S4' "POST /api/ask  $q4"
$r4 = Invoke-Ask $q4
$gate = $r4.rejected.gate
$reason = $r4.rejected.reason
Write-Host "  rejected.gate=$gate"
Write-Host "  rejected.reason=$(Get-Snippet ([string]$reason) 120)"
Assert-That 'S4a' 'rejected.gate == write_intent' ($gate -eq 'write_intent') "got=$gate"
Assert-That 'S4b' '返回 rows 为空（未执行 SQL）' (@($r4.rows).Count -eq 0) "row_count=$($r4.row_count) sql=$($r4.sql)"

# ---------- 汇总 ----------
Write-Host ""
Write-Host ("RESULT: {0} ({1}/{2} 断言通过)" -f $(if ($script:failed -eq 0) { 'PASS' } else { 'FAIL' }), $script:passed, ($script:passed + $script:failed))
if ($script:failed -eq 0) { exit 0 } else { exit 1 }
