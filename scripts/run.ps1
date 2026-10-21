<#
.SYNOPSIS
  启动指定案例的 Web 服务（缺数据时先自动生成）。
.EXAMPLE
  .\scripts\run.ps1 -Case 1
  .\scripts\run.ps1 -Case 3 -Port 5182
#>
param(
    [Parameter(Mandatory = $true)][ValidateSet('1', '2', '3')][string]$Case,
    [int]$Port = 0
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$map = @{
    '1' = @{ dir = 'cases\01-rag-qa'; default = 4180 }
    '2' = @{ dir = 'cases\02-nl2sql'; default = 4181 }
    '3' = @{ dir = 'cases\03-contract-review'; default = 4182 }
}
$c = $map[$Case]
$dir = $c.dir
if (-not (Test-Path (Join-Path $dir '.env'))) {
    Write-Host ("[失败] {0}\.env 不存在，先跑 .\scripts\setup.ps1" -f $dir) -ForegroundColor Red
    exit 1
}
$vpy = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $vpy)) {
    Write-Host "[失败] 缺少 .venv，先跑 .\scripts\setup.ps1" -ForegroundColor Red
    exit 1
}

# 缺数据时自动生成（确定性脚本，不需要 key）
Push-Location $dir
if ($Case -eq '1') {
    if (-not (Test-Path 'data\index\meta.json')) {
        Write-Host "索引缺失，先建索引（需要 key，315 chunk）…" -ForegroundColor Cyan
        & $vpy -m src.ingest
        if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
    }
}
if ($Case -eq '2') {
    if (-not (Test-Path 'data\aicoding.db')) {
        Write-Host "数据库缺失，生成中…" -ForegroundColor Cyan
        & $vpy -m scripts.gen_db
    }
}
if ($Case -eq '3') {
    $n = @(Get-ChildItem 'data\contracts' -Filter *.docx -ErrorAction SilentlyContinue).Count
    if ($n -lt 30) {
        Write-Host "合同缺失，生成 30 份…" -ForegroundColor Cyan
        & $vpy -m scripts.gen_contracts
    }
}
Pop-Location

$usePort = if ($Port -gt 0) { $Port } else { $c.default }
$env:PORT = "$usePort"
Write-Host ("启动案例 {0}：http://127.0.0.1:{1}  （Ctrl+C 停止）" -f $Case, $usePort) -ForegroundColor Green
Push-Location $dir
try {
    & $vpy -m src.server
} finally {
    Pop-Location
}
