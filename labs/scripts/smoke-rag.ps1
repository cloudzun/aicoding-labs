<#
.SYNOPSIS
  案例一 政企 RAG 问答 · 5 分钟自检脚本（HANDOFF §4.1 逐字实现）
.DESCRIPTION
  前置：cd cases\01-rag-qa; python -m src.server（监听 4180）
  三步断言：
    S1  GET /api/health        -> index.chunk_count = 315，index.embed_dim = 2560
    S2  "单笔采购金额500万元以上的采购项目，需要提交什么会议审议？"
                               -> 答案文本同时含 "500" 与 "废止"
    S3  "员工的婚假有多少天？"  -> done.refused = true；答案含 "资料不足"；elapsed_ms < 2000
  输出：每步 [PASS]/[FAIL]，末尾 RESULT；全过 exit 0，否则 exit 1。
  说明：脚本只做读取与提问，不写业务数据；SSE 用 HttpClient 读原始字节后按 UTF-8 解码，避免中文乱码。
#>
[CmdletBinding()]
param(
    [int]$Port = 4180,
    [int]$TimeoutSec = 180
)

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

function Invoke-RagChat([string]$Question) {
    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSec)
    $json = @{ question = $Question; history = @() } | ConvertTo-Json -Compress -Depth 5
    $content = [System.Net.Http.StringContent]::new($json, [System.Text.Encoding]::UTF8, 'application/json')
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $resp = $client.PostAsync("$base/api/chat", $content).GetAwaiter().GetResult()
    $bytes = $resp.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
    $sw.Stop()
    $client.Dispose()
    $raw = [System.Text.Encoding]::UTF8.GetString($bytes)

    $answer = ''
    $done = $null
    $evt = ''
    foreach ($line in ($raw -split "`n")) {
        $l = $line.TrimEnd("`r")
        if ($l.StartsWith('event: ')) { $evt = $l.Substring(7).Trim() }
        elseif ($l.StartsWith('data: ')) {
            $payload = $l.Substring(6) | ConvertFrom-Json
            if ($evt -eq 'delta') { $answer += [string]$payload.text }
            elseif ($evt -eq 'done') { $done = $payload }
            elseif ($evt -eq 'error') { throw "SSE error: $($payload.error)" }
        }
    }
    return [pscustomobject]@{ Answer = $answer; Done = $done; WallMs = $sw.ElapsedMilliseconds }
}

function Get-Snippet([string]$text, [int]$n = 160) {
    $flat = ($text -replace '\s+', ' ').Trim()
    if ($flat.Length -le $n) { return $flat }
    return $flat.Substring(0, $n) + '…'
}

Write-Host "SMOKE-RAG  base=$base  time=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

# ---------- S0 可达性（不计入断言，只做快速失败） ----------
try {
    $health = Invoke-RestMethod -Uri "$base/api/health" -TimeoutSec 15
} catch {
    Write-Host "[FAIL] S0 服务不可达：$base/api/health -> $($_.Exception.Message)"
    Write-Host "RESULT: FAIL (0/0) — 先启动服务：cd cases\01-rag-qa; python -m src.server"
    exit 1
}

# ---------- S1 health ----------
Write-Step 'S1' 'GET /api/health'
$chunk = $health.index.chunk_count
$dim = $health.index.embed_dim
Write-Host "  chunk_count=$chunk  embed_dim=$dim  docs=$($health.index.docs)  embed_model=$($health.index.embed_model)"
Assert-That 'S1a' '.index.chunk_count == 315' ($chunk -eq 315) "got=$chunk"
Assert-That 'S1b' '.index.embed_dim == 2560' ($dim -eq 2560) "got=$dim"

# ---------- S2 主问题：必须同时含 500 与 废止 ----------
$q2 = '单笔采购金额500万元以上的采购项目，需要提交什么会议审议？'
Write-Step 'S2' "POST /api/chat  $q2"
$r2 = Invoke-RagChat $q2
$ans2 = [string]$r2.Answer
Write-Host "  elapsed_ms=$($r2.Done.elapsed_ms)  wall_ms=$($r2.WallMs)  refused=$($r2.Done.refused)  trace_id=$($r2.Done.trace_id)"
Write-Host "  answer(片段)=$(Get-Snippet $ans2 200)"
Assert-That 'S2a' '答案含 "500"' ($ans2 -match '500') "len=$($ans2.Length)"
Assert-That 'S2b' '答案含 "废止"' ($ans2 -match '废止') "len=$($ans2.Length)"

# ---------- S3 拒答：refused=true / 含资料不足 / < 2000ms ----------
$q3 = '员工的婚假有多少天？'
Write-Step 'S3' "POST /api/chat  $q3"
$r3 = Invoke-RagChat $q3
$ans3 = [string]$r3.Answer
$ms3 = $r3.Done.elapsed_ms
Write-Host "  elapsed_ms=$ms3  wall_ms=$($r3.WallMs)  refused=$($r3.Done.refused)  trace_id=$($r3.Done.trace_id)"
Write-Host "  answer(片段)=$(Get-Snippet $ans3 200)"
Assert-That 'S3a' 'done.refused == true' ($r3.Done.refused -eq $true) "got=$($r3.Done.refused)"
Assert-That 'S3b' '答案含 "资料不足"' ($ans3 -match '资料不足') "len=$($ans3.Length)"
Assert-That 'S3c' 'done.elapsed_ms < 2000' ($null -ne $ms3 -and [int]$ms3 -lt 2000) "got=${ms3}ms"

# ---------- 汇总 ----------
Write-Host ""
Write-Host ("RESULT: {0} ({1}/{2} 断言通过)" -f $(if ($script:failed -eq 0) { 'PASS' } else { 'FAIL' }), $script:passed, ($script:passed + $script:failed))
if ($script:failed -eq 0) { exit 0 } else { exit 1 }
