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
$env:PYTHONUTF8 = '1'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$cases = @('01-rag-qa', '02-nl2sql', '03-contract-review')

Write-Host "== 1/4 检查 Python ==" -ForegroundColor Cyan
# 注意：某些安装方式（如 Chocolatey/Windows 应用别名）会在 PATH 里放一个 shim，
# 直接调用时 Python 可能把"当前目录"误当成安装前缀（报 No module named 'encodings'）。
# 因此逐个候选解释器做一次真实导入测试，选第一个能正常启动的。
$candidates = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $candidates += @{ exe = 'py'; args = @('-3.12') }
    $candidates += @{ exe = 'py'; args = @('-3') }
}
$candidates += @{ exe = 'python'; args = @() }
$candidates += @{ exe = 'python3'; args = @() }

$interp = $null
foreach ($cand in $candidates) {
    if (-not (Get-Command $cand.exe -ErrorAction SilentlyContinue)) { continue }
    try {
        $probeArgs = @($cand.args) + @('-c', 'import sys,encodings;print(sys.version_info[0], sys.version_info[1])')
        $out = & $cand.exe @probeArgs 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            $interp = $cand
            Write-Host ("  python {0}（{1}）" -f (($out | Select-Object -First 1) -replace ' ', '.'), $cand.exe)
            break
        }
    } catch { }
}
if (-not $interp) {
    # 兜底：直接尝试常见安装目录（绕过 PATH 里的 shim）
    $common = @(
        'C:\Python312\python.exe',
        (Join-Path $env:ProgramFiles 'Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        'C:\Python311\python.exe',
        (Join-Path $env:ProgramFiles 'Python311\python.exe')
    )
    foreach ($exe in $common) {
        if (-not (Test-Path $exe)) { continue }
        try {
            $out = & $exe -c 'import sys,encodings;print(sys.version_info[0], sys.version_info[1])' 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) {
                $interp = @{ exe = $exe; args = @() }
                Write-Host ("  python {0}（{1}）" -f (($out | Select-Object -First 1) -replace ' ', '.'), $exe)
                break
            }
        } catch { }
    }
}
if (-not $interp) {
    Write-Host "[失败] 找不到可用的 Python（需 3.10+，建议 3.12）。" -ForegroundColor Red
    Write-Host "  安装后若仍报 No module named 'encodings'，说明 PATH 里是 shim：" -ForegroundColor Yellow
    Write-Host "  改用完整路径调用，例如 C:\Python312\python.exe -m venv .venv" -ForegroundColor Yellow
    exit 1
}

Write-Host "== 2/4 创建虚拟环境 .venv ==" -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $root '.venv'))) {
    & $interp.exe @(@($interp.args) + @('-m', 'venv', '.venv'))
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
