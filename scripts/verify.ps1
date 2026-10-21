<#
.SYNOPSIS
  验收：不依赖 key 的离线断言（CI 同款），可选联网冒烟。
.DESCRIPTION
  离线部分（默认）：
    - 全部 .py 语法编译
    - 案例二 gen_db + verify_db（11 项断言）
    - 案例三 gen_contracts + verify_data（10 项断言）
    - 密钥扫描
  加 -WithNetwork 时额外做一次真实模型调用（需要 .env 里已填 key）。
.EXAMPLE
  .\scripts\verify.ps1
  .\scripts\verify.ps1 -WithNetwork
#>
param([switch]$WithNetwork)

$ErrorActionPreference = 'Continue'
$env:PYTHONUTF8 = '1'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$vpy = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $vpy)) {
    Write-Host "[失败] 缺少 .venv，请先运行 .\scripts\setup.ps1" -ForegroundColor Red
    exit 1
}

$fail = 0
function Step($name) { Write-Host ""; Write-Host "== $name ==" -ForegroundColor Cyan }
function Pass($m) { Write-Host "  [PASS] $m" -ForegroundColor Green }
function Fail($m) { Write-Host "  [FAIL] $m" -ForegroundColor Red; $script:fail++ }

Step "1/5 Python 语法"
$pyFiles = Get-ChildItem . -Recurse -File -Filter *.py | Where-Object { $_.FullName -notmatch '\\\.venv\\' }
$bad = 0
foreach ($f in $pyFiles) {
    & $vpy -m py_compile $f.FullName 2>$null
    if ($LASTEXITCODE -ne 0) { $bad++; Fail "编译失败：$($f.FullName.Replace($root + '\', ''))" }
}
if ($bad -eq 0) { Pass ("{0} 个 .py 全部通过" -f $pyFiles.Count) }

Step "2/5 案例二 数据生成与断言"
Push-Location 'cases\02-nl2sql'
& $vpy -m scripts.gen_db 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Pass "gen_db 退出码 0" } else { Fail "gen_db 失败" }
$out = & $vpy -m scripts.verify_db 2>&1 | Out-String
$passCount = ([regex]::Matches($out, '\[PASS\]')).Count
if ($LASTEXITCODE -eq 0 -and $passCount -ge 11) { Pass ("verify_db {0}/11 通过" -f $passCount) } else { Fail ("verify_db 异常（PASS {0} 条）" -f $passCount) }
Pop-Location

Step "3/5 案例三 数据生成与断言"
Push-Location 'cases\03-contract-review'
& $vpy -m scripts.gen_contracts 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Pass "gen_contracts 退出码 0" } else { Fail "gen_contracts 失败" }
$out = & $vpy -m scripts.verify_data 2>&1 | Out-String
$passCount = ([regex]::Matches($out, '\[PASS\]')).Count
if ($LASTEXITCODE -eq 0 -and $passCount -ge 10) { Pass ("verify_data {0}/10 通过" -f $passCount) } else { Fail ("verify_data 异常（PASS {0} 条）" -f $passCount) }
Pop-Location

Step "4/5 案例一 索引与语料一致性"
$metaPath = 'cases\01-rag-qa\data\index\meta.json'
if (Test-Path $metaPath) {
    $m = Get-Content $metaPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($m.chunk_count -eq 315 -and $m.embed_dim -eq 2560) { Pass ("索引 {0} chunk / {1} 维" -f $m.chunk_count, $m.embed_dim) }
    else { Fail ("索引异常：{0} chunk / {1} 维（期望 315 / 2560）" -f $m.chunk_count, $m.embed_dim) }
    $docs = @(Get-ChildItem 'cases\01-rag-qa\data\corpus\synthetic' -Filter *.md -ErrorAction SilentlyContinue).Count
    if ($docs -eq 13) { Pass "语料 13 个文件（12 篇制度 + 埋点登记）" } else { Fail ("语料文件数 {0}（期望 13）" -f $docs) }
} else {
    # 索引依赖嵌入服务、需要 key，因此不随仓库分发；缺失只提醒，不算失败
    Write-Host "  [WARN] 索引尚未生成（需要 key）：cd cases\01-rag-qa; python -m src.ingest" -ForegroundColor Yellow
    $docs = @(Get-ChildItem 'cases\01-rag-qa\data\corpus\synthetic' -Filter *.md -ErrorAction SilentlyContinue).Count
    if ($docs -eq 13) { Pass "语料 13 个文件（12 篇制度 + 埋点登记）" } else { Fail ("语料文件数 {0}（期望 13）" -f $docs) }
}

Step "5/5 密钥扫描"
& (Join-Path $PSScriptRoot 'check-secrets.ps1') | Out-Host
if ($LASTEXITCODE -ne 0) { Fail "密钥扫描未通过" } else { Pass "无真实密钥" }

if ($WithNetwork) {
    Step "附加：联网冒烟（各案例一次模型调用）"
    $tmp = Join-Path $env:TEMP ("verify-smoke-" + [guid]::NewGuid().ToString('N') + ".py")
    foreach ($pair in @(@('1', 'cases\01-rag-qa'), @('2', 'cases\02-nl2sql'), @('3', 'cases\03-contract-review'))) {
        $k = $pair[0]; $d = $pair[1]
        # 案例一没有 src/llm.py，用 generate.chat；其余用 llm.chat
        $mod = if ($k -eq '1') { 'generate' } else { 'llm' }
        $code = @"
import os, sys
sys.path.insert(0, os.getcwd())
from src import $mod
try:
    out = $mod.chat([{'role': 'user', 'content': '只回复 OK 两个字母'}], max_tokens=8, timeout_s=30)
    print('OK' if out.get('content') else 'EMPTY')
except Exception as e:
    print('ERR:' + type(e).__name__ + ':' + str(e)[:80])
"@
        [System.IO.File]::WriteAllText($tmp, $code, (New-Object System.Text.UTF8Encoding($false)))
        Push-Location $d
        $res = & $vpy $tmp 2>&1 | Select-Object -Last 1
        Pop-Location
        if ("$res" -match '^OK') { Pass ("案例{0} 模型调用成功" -f $k) } else { Fail ("案例{0} 模型调用失败：{1}" -f $k, $res) }
    }
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}

Write-Host ""
if ($fail -eq 0) { Write-Host "验收通过。" -ForegroundColor Green; exit 0 }
Write-Host ("验收失败：{0} 项。" -f $fail) -ForegroundColor Red
exit 1
