<#
.SYNOPSIS
  提交前自检：仓库里不应出现真实密钥。
.DESCRIPTION
  只扫描 git 跟踪的文件（git ls-files），避免误报本地 .env。
  命中退出码 1；干净退出码 0。CI 也跑同一脚本。
.EXAMPLE
  .\scripts\check-secrets.ps1
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$files = git -c core.quotepath=false ls-files | ForEach-Object { $_.Trim('"') }
if (-not $files) { Write-Host "[失败] 当前目录不是 git 仓库" -ForegroundColor Red; exit 1 }

$bad = @()
foreach ($f in $files) {
    if ($f -match '(^|/)\.env$') { $bad += "$f  ← .env 被纳入版本控制"; continue }
    if (-not (Test-Path $f)) { continue }
    $item = Get-Item $f
    if ($item.Length -gt 2MB) { continue }
    try { $text = [System.IO.File]::ReadAllText((Resolve-Path $f), [System.Text.Encoding]::UTF8) } catch { continue }
    if ($text -match '(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{20,}') { $bad += "$f  ← 疑似密钥（sk-...）" }
    if ($text -match 'SILICONFLOW_KEY=[^\s<]' -and $text -notmatch 'SILICONFLOW_KEY=<') { $bad += "$f  ← SILICONFLOW_KEY 有真实值" }
    if ($text -match 'MAGPIE_KEY=[^\s<$]' -and $text -notmatch 'MAGPIE_KEY=<') { $bad += "$f  ← MAGPIE_KEY 有真实值" }
}

if ($bad.Count -eq 0) {
    Write-Host ("[通过] {0} 个跟踪文件，未发现真实密钥" -f $files.Count) -ForegroundColor Green
    exit 0
}
Write-Host "[失败] 发现疑似密钥：" -ForegroundColor Red
$bad | ForEach-Object { Write-Host "  $_" }
exit 1
