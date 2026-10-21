<#
.SYNOPSIS
  体检：逐项检查环境，红/绿清单 + 可读的修复建议。
.DESCRIPTION
  静态标本没有人工答疑，这个脚本就是"客服"：
  无 key / key 错 / 连不上 / 端口占用 / 嵌入维度不符，都给中文提示。
  不修改任何文件。
.EXAMPLE
  .\scripts\doctor.ps1
  .\scripts\doctor.ps1 -Case 1
#>
param([ValidateSet('1', '2', '3', 'all')][string]$Case = 'all')

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$fail = 0
$warn = 0
function Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "  [FAIL] $m" -ForegroundColor Red; $script:fail++ }
function Warn($m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow; $script:warn++ }

Write-Host "== 1. Python 与虚拟环境 ==" -ForegroundColor Cyan
$vpy = Join-Path $root '.venv\Scripts\python.exe'
if (Test-Path $vpy) {
    $ver = & $vpy -c "import sys;print('.'.join(map(str,sys.version_info[:3])))"
    Ok ".venv 存在（Python $ver）"
} else {
    Bad "缺少 .venv，请先运行 .\scripts\setup.ps1"
    $vpy = 'python'
}

Write-Host "== 2. 读取各案例 .env ==" -ForegroundColor Cyan
$cases = @{ '1' = '01-rag-qa'; '2' = '02-nl2sql'; '3' = '03-contract-review' }
$selected = if ($Case -eq 'all') { @('1', '2', '3') } else { @($Case) }

function Read-EnvFile([string]$path) {
    $h = @{}
    if (Test-Path $path) {
        foreach ($line in Get-Content $path -Encoding UTF8) {
            $t = $line.Trim()
            if (-not $t -or $t.StartsWith('#') -or -not $t.Contains('=')) { continue }
            $k, $v = $t.Split('=', 2)
            $h[$k.Trim()] = $v.Trim()
        }
    }
    return $h
}

foreach ($k in $selected) {
    $dir = "cases\$($cases[$k])"
    $envPath = Join-Path $dir '.env'
    if (-not (Test-Path $envPath)) { Bad "$dir 缺少 .env（复制 .env.example 或跑 setup.ps1）"; continue }
    $e = Read-EnvFile $envPath
    $provider = if ($e['LLM_PROVIDER']) { $e['LLM_PROVIDER'] } else { 'siliconflow' }
    if ($provider -eq 'magpie') {
        $base = $e['MAGPIE_BASE']; $key = $e['MAGPIE_KEY']
        if (-not $base) { Bad "案例$k：magpie 档缺 MAGPIE_BASE" }
    } else {
        $base = $e['SILICONFLOW_BASE']; $key = $e['SILICONFLOW_KEY']
    }
    if (-not $key -or $key -match '^<') { Bad "案例$k：未填 API key（当前仍为占位符）"; continue }
    Ok ("案例{0}：供应商 {1}，key 已填（{2} 字符）" -f $k, $provider, $key.Length)
    $global:LastBase = $base
    $global:LastKey = $key
    $global:LastProvider = $provider
}

Write-Host "== 3. 网络与模型可用性 ==" -ForegroundColor Cyan
if ($global:LastKey) {
    $base = $global:LastBase
    if (-not $base) { Bad "未读到 base（检查 .env）" }
    else {
        try {
            $hdr = @{ Authorization = "Bearer $($global:LastKey)" }
            $models = Invoke-RestMethod -Uri "$base/models" -Headers $hdr -TimeoutSec 20
            Ok ("/models 可达，共 {0} 个模型" -f @($models.data).Count)
            $ids = @($models.data | ForEach-Object { $_.id })
            $need = @()
            if ($selected -contains '1') { $need += @('Qwen/Qwen3-Embedding-4B', 'Qwen/Qwen3-Reranker-4B') }
            foreach ($m in $need) {
                if ($ids -contains $m) { Ok "模型存在：$m" } else { Warn "默认模型缺失：$m（模型可能已下架，改 .env 换同名替代）" }
            }
        } catch {
            Bad "连不上模型服务：$($_.Exception.Message)"
            Write-Host "       检查网络/代理，或确认 base 写成 https://api.siliconflow.cn/v1" -ForegroundColor DarkGray
        }
    }
} else {
    Warn "跳过网络检查（没有可用 key）"
}

Write-Host "== 4. 端口占用 ==" -ForegroundColor Cyan
$ports = @{ '01-rag-qa' = 4180; '02-nl2sql' = 4181; '03-contract-review' = 4182 }
foreach ($c in $cases.Values) {
    $p = $ports[$c]
    $used = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($used) { Warn "端口 $p 已被占用（案例 $c）；可在 .env 改 PORT" } else { Ok "端口 $p 可用（$c）" }
}

Write-Host "== 5. 数据与索引 ==" -ForegroundColor Cyan
if ($selected -contains '1') {
    $meta = 'cases\01-rag-qa\data\index\meta.json'
    if (Test-Path $meta) {
        $m = Get-Content $meta -Raw -Encoding UTF8 | ConvertFrom-Json
        Ok ("索引就绪：{0} chunk / {1} 维 / 模型 {2}" -f $m.chunk_count, $m.embed_dim, $m.embed_model)
        $e = Read-EnvFile 'cases\01-rag-qa\.env'
        if ($e['EMBED_MODEL'] -and $e['EMBED_MODEL'] -ne $m.embed_model) {
            Warn ("索引模型({0}) 与 .env EMBED_MODEL({1}) 不一致；换模型后必须 python -m src.ingest 重建" -f $m.embed_model, $e['EMBED_MODEL'])
        }
    } else { Warn "案例一索引缺失：先 cd cases\01-rag-qa; python -m src.ingest" }
}
if ($selected -contains '2') {
    if (Test-Path 'cases\02-nl2sql\data\aicoding.db') { Ok "案例二数据库已生成" }
    else { Warn "案例二数据库缺失：cd cases\02-nl2sql; python -m scripts.gen_db" }
}
if ($selected -contains '3') {
    $n = @(Get-ChildItem 'cases\03-contract-review\data\contracts' -Filter *.docx -ErrorAction SilentlyContinue).Count
    if ($n -ge 30) { Ok "案例三合同已生成（$n 份）" } else { Warn "案例三合同缺失或不足（$n 份）：python -m scripts.gen_contracts" }
}

Write-Host ""
if ($fail -eq 0) {
    Write-Host ("体检通过（警告 {0} 条）。下一步：.\scripts\run.ps1 -Case 1" -f $warn) -ForegroundColor Green
    exit 0
}
Write-Host ("体检未通过：{0} 个硬错误、{1} 条警告。按上面 [FAIL] 的提示逐条修。" -f $fail, $warn) -ForegroundColor Red
exit 1
