<#
.SYNOPSIS
  案例三 合同审查 · 5 分钟自检脚本（HANDOFF §4.1 逐字实现）
.DESCRIPTION
  前置：cd cases\03-contract-review; python -m src.server（监听 4182）
  四步断言：
    S1  python -m scripts.gen_contracts; python -m scripts.verify_data
        -> 10 行 [PASS]，共 810 单元
    S2  审 CT001（with_semantic 默认 true）-> summary 高/中/低/必查缺失 全 0
    S3  审 CT003                            -> findings 必含 R02（中）与 R19（高）
    S4  审 CT003，with_semantic=false       -> coverage.not_detected 含 R20–R25 六条
  输出：每步 [PASS]/[FAIL]，末尾 RESULT；全过 exit 0，否则 exit 1。
  注意：S1 会重建 30 份 docx 并覆写 data/manifest.json（HANDOFF §4.2 允许，事后须与 frozen-manifest 比对）。
#>
[CmdletBinding()]
param(
    [int]$Port = 4182,
    [int]$TimeoutSec = 600,
    [string]$ProjectDir = ''
)

# PS 5.1 下 $PSScriptRoot 在 param 默认值求值时为空，故在 param 之后解析项目目录
if (-not $ProjectDir) {
    $ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..\cases\03-contract-review')).Path
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
# ISO-8859-1 解无 charset 的 JSON，中文会变乱码（影响 summary.高/中/低 与 level 比对）。
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

function Invoke-Review([string]$ContractId, [bool]$WithSemantic) {
    return Invoke-Json '/api/review' @{ contract_id = $ContractId; with_semantic = $WithSemantic } $TimeoutSec
}

Write-Host "SMOKE-CONTRACT  base=$base  project=$ProjectDir  time=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

# ---------- S0 可达性（不计入断言） ----------
try {
    $health = Invoke-Json '/api/health' $null 15
} catch {
    Write-Host "[FAIL] S0 服务不可达：$base/api/health -> $($_.Exception.Message)"
    Write-Host "RESULT: FAIL (0/0) — 先启动服务：cd cases\03-contract-review; python -m src.server"
    exit 1
}

# ---------- S1 重建 + 10 项数据断言 ----------
Write-Step 'S1' 'python -m scripts.gen_contracts; python -m scripts.verify_data'
$env:PYTHONIOENCODING = 'utf-8'
$oldEnc = [Console]::OutputEncoding
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
Push-Location $ProjectDir
# 原生命令的 stderr 在 $ErrorActionPreference='Stop' 下会被当成终止错误抛出，
# 这里局部放宽为 Continue，让 S1 的失败被"记录"而不是"中断"，便于继续取证 S2–S4。
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    $genOut = (& python -m scripts.gen_contracts 2>&1 | Out-String)
    $genCode = $LASTEXITCODE
    $verOut = (& python -m scripts.verify_data 2>&1 | Out-String)
    $verCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $prevEap
    Pop-Location
    try { [Console]::OutputEncoding = $oldEnc } catch { }
}
if ($null -eq $verOut) { $verOut = '' }
if ($null -eq $genOut) { $genOut = '' }
Write-Host "  gen_contracts exit=$genCode"
Write-Host "  $(Get-Snippet $genOut 200)"
Write-Host "  verify_data exit=$verCode"
foreach ($line in ($verOut -split "`n")) { if ($line.Trim()) { Write-Host "  $($line.TrimEnd())" } }

$passLines = ($verOut -split "`n" | Where-Object { $_ -match '^\[PASS\]' }).Count
Assert-That 'S1a' 'gen_contracts 退出码 = 0' ($genCode -eq 0) "exit=$genCode"
Assert-That 'S1b' 'verify_data 输出 10 行 [PASS]' ($passLines -eq 10) "got=$passLines"
Assert-That 'S1c' '输出含 810 单元' ($verOut -match '810') "match=$($verOut -match '810')"
Assert-That 'S1d' 'verify_data 退出码 = 0' ($verCode -eq 0) "exit=$verCode"

# ---------- S2 CT001 零风险 ----------
Write-Step 'S2' 'POST /api/review  {"contract_id":"CT001","with_semantic":true}'
$r2 = Invoke-Review 'CT001' $true
$s = $r2.summary
Write-Host "  summary: 高=$($s.'高') 中=$($s.'中') 低=$($s.'低') 必查缺失=$($s.'必查缺失')"
Write-Host "  findings=$(@($r2.findings).Count)  coverage.not_detected=$((@($r2.coverage.not_detected)) -join ',')"
Assert-That 'S2a' 'summary.高 == 0' ([int]$s.'高' -eq 0) "got=$($s.'高')"
Assert-That 'S2b' 'summary.中 == 0' ([int]$s.'中' -eq 0) "got=$($s.'中')"
Assert-That 'S2c' 'summary.低 == 0' ([int]$s.'低' -eq 0) "got=$($s.'低')"
Assert-That 'S2d' 'summary.必查缺失 == 0' ([int]$s.'必查缺失' -eq 0) "got=$($s.'必查缺失')"

# ---------- S3 CT003 必含 R02（中）与 R19（高） ----------
Write-Step 'S3' 'POST /api/review  {"contract_id":"CT003","with_semantic":true}'
$r3 = Invoke-Review 'CT003' $true
$findings = @($r3.findings)
Write-Host "  summary: 高=$($r3.summary.'高') 中=$($r3.summary.'中') 低=$($r3.summary.'低') 必查缺失=$($r3.summary.'必查缺失')"
Write-Host "  命中规则=$(($findings | ForEach-Object { "$($_.rule_id)/$($_.level)" }) -join ',')"
$r02 = $findings | Where-Object { $_.rule_id -eq 'R02' -and $_.violated } | Select-Object -First 1
$r19 = $findings | Where-Object { $_.rule_id -eq 'R19' -and $_.violated } | Select-Object -First 1
Assert-That 'S3a' 'findings 含 R02 且 violated' ($null -ne $r02) "found=$($null -ne $r02)"
Assert-That 'S3b' 'R02 level == 中' ($null -ne $r02 -and $r02.level -eq '中') "got=$($r02.level)"
Assert-That 'S3c' 'findings 含 R19 且 violated' ($null -ne $r19) "found=$($null -ne $r19)"
Assert-That 'S3d' 'R19 level == 高' ($null -ne $r19 -and $r19.level -eq '高') "got=$($r19.level)"

# ---------- S4 关语义：not_detected 显式列出 R20–R25 ----------
Write-Step 'S4' 'POST /api/review  {"contract_id":"CT003","with_semantic":false}'
$r4 = Invoke-Review 'CT003' $false
$nd = @($r4.coverage.not_detected)
Write-Host "  coverage: rules_total=$($r4.coverage.rules_total) rules_checked=$($r4.coverage.rules_checked)"
Write-Host "  not_detected=$($nd -join ',')"
$semantic = @('R20', 'R21', 'R22', 'R23', 'R24', 'R25')
$missing = @($semantic | Where-Object { $nd -notcontains $_ })
Assert-That 'S4a' 'not_detected 含 R20–R25 全部 6 条' ($missing.Count -eq 0) "missing=$($missing -join ',')"

# ---------- 汇总 ----------
Write-Host ""
Write-Host ("RESULT: {0} ({1}/{2} 断言通过)" -f $(if ($script:failed -eq 0) { 'PASS' } else { 'FAIL' }), $script:passed, ($script:passed + $script:failed))
if ($script:failed -eq 0) { exit 0 } else { exit 1 }
