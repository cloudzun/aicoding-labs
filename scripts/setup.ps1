<#
.SYNOPSIS
  一键准备运行环境：建 .venv、装三个案例的依赖、按需生成 .env。
.DESCRIPTION
  幂等：重复运行不会覆盖已存在的 .env（除非 -Force）。
  不联网下载模型；不做任何模型调用（key 由使用者自己填）。
.EXAMPLE
  .\scripts\setup.ps1
  .\scripts\setup.ps1 -Force
#>
param([switch]$Force)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$cases = @('01-rag-qa', '02-nl2sql', '03-contract-review')

Write-Host "== 1/4 检查 Python ==" -ForegroundColor Cyan
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) {
    Write-Host "[失败] 找不到 python。请安装 Python 3.12 并勾选 Add to PATH。" -ForegroundColor Red
    exit 1
}
$ver = & python -c "import sys;print('.'.join(map(str,sys.version_info[:2])))"
Write-Host ("  python {0}（建议 3.12）" -f $ver)

Write-Host "== 2/4 创建虚拟环境 .venv ==" -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $root '.venv'))) {
    & python -m venv .venv
} else {
    Write-Host "  .venv 已存在，复用"
}
$vpy = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $vpy)) { Write-Host "[失败] .venv 创建失败" -ForegroundColor Red; exit 1 }

Write-Host "== 3/4 安装依赖 ==" -ForegroundColor Cyan
& $vpy -m pip install --quiet --upgrade pip
foreach ($c in $cases) {
    $req = Join-Path $root "cases\$c\requirements.txt"
    Write-Host ("  安装 {0}" -f $c)
    & $vpy -m pip install --quiet -r $req
    if ($LASTEXITCODE -ne 0) { Write-Host ("[失败] {0} 依赖安装失败" -f $c) -ForegroundColor Red; exit 1 }
}

Write-Host "== 4/4 准备 .env ==" -ForegroundColor Cyan
foreach ($c in $cases) {
    $envPath = Join-Path $root "cases\$c\.env"
    if ((Test-Path $envPath) -and (-not $Force)) {
        Write-Host ("  {0}: 已存在，跳过" -f $c)
        continue
    }
    Copy-Item (Join-Path $root '.env.example') $envPath -Force
    Write-Host ("  {0}: 已生成 cases\{0}\.env  ← 请填入 SILICONFLOW_KEY" -f $c)
}

Write-Host ""
Write-Host "完成。下一步：" -ForegroundColor Green
Write-Host "  1) 编辑 cases\*\..env，把 <YOUR_SILICONFLOW_KEY> 换成你的 key"
Write-Host "  2) 运行 .\scripts\doctor.ps1 体检"
Write-Host "  3) 运行 .\scripts\run.ps1 -Case 1"
