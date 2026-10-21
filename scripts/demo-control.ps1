<#
.SYNOPSIS
  三个案例的一键启停与状态体检（后台运行）。
.DESCRIPTION
  管理 4180（RAG）/ 4181（NL2SQL）/ 4182（合同审查）三个服务：
    status   查看端口 / PID / 内存 / 健康 / 运行时长
    start    后台启动，等待 /api/health 就绪；缺数据时先自动生成（案例一索引需 key）
    stop     只停"命令行里带 src.server 的 python 进程"，避免误杀其他 python
    restart  先停后起（演示前推荐）
  端口取各案例 .env 的 PORT，缺省 4180/4181/4182；优先用仓库根目录的 .venv。
.EXAMPLE
  .\scripts\demo-control.ps1 status
  .\scripts\demo-control.ps1 start
  .\scripts\demo-control.ps1 stop
  .\scripts\demo-control.ps1 restart -Case 1
#>
[CmdletBinding()]
param(
    [ValidateSet('status', 'start', 'stop', 'restart')]
    [string]$Action = 'status',
    [ValidateSet('1', '2', '3', 'all')]
    [string]$Case = 'all'
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$cases = @{
    '1' = @{ dir = 'cases\01-rag-qa';         port = 4180; name = 'RAG 制度问答' }
    '2' = @{ dir = 'cases\02-nl2sql';         port = 4181; name = 'NL2SQL 问数' }
    '3' = @{ dir = 'cases\03-contract-review'; port = 4182; name = '合同审查' }
}

$vpy = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $vpy)) { $vpy = 'python' }

function Get-CasePort([string]$key) {
    $envFile = Join-Path $root "$($cases[$key].dir)\.env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile -Encoding UTF8) {
            if ($line -match '^\s*PORT\s*=\s*(\d+)') { return [int]$Matches[1] }
        }
    }
    return $cases[$key].port
}

function Get-Listener([int]$port) {
    return Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Get-Health([int]$port) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/health" -UseBasicParsing -TimeoutSec 5
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Get-IsOurServer([int]$pidValue) {
    try {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction Stop
        return ($p.Name -match '^python' -and $p.CommandLine -match 'src\.server')
    } catch { return $false }
}

function Show-Status {
    Write-Host ("{0,-16} {1,-6} {2,-7} {3,-8} {4,-6} {5}" -f '服务', '端口', 'PID', '内存MB', '健康', '运行时长')
    Write-Host ('-' * 66)
    foreach ($k in $cases.Keys | Sort-Object) {
        $port = Get-CasePort $k
        $l = Get-Listener $port
        if (-not $l) {
            Write-Host ("{0,-16} {1,-6} {2,-7} {3,-8} {4,-6} {5}" -f $cases[$k].name, $port, '-', '-', 'DOWN', '-')
            continue
        }
        $proc = Get-Process -Id $l.OwningProcess -ErrorAction SilentlyContinue
        $up = if ($proc) { ((Get-Date) - $proc.StartTime).ToString('hh\:mm') } else { '?' }
        $mem = if ($proc) { [math]::Round($proc.WorkingSet64 / 1MB, 0) } else { '-' }
        Write-Host ("{0,-16} {1,-6} {2,-7} {3,-8} {4,-6} {5}" -f $cases[$k].name, $port, $l.OwningProcess, $mem,
            $(if (Get-Health $port) { 'OK' } else { 'ERR' }), $up)
    }
}

function Ensure-Data([string]$k) {
    Push-Location $cases[$k].dir
    try {
        if ($k -eq '1' -and -not (Test-Path 'data\index\meta.json')) {
            Write-Host '  案例一索引缺失，先建索引（需要 key，约 1 分钟）…' -ForegroundColor Cyan
            & $vpy -m src.ingest
        }
        if ($k -eq '2' -and -not (Test-Path 'data\aicoding.db')) {
            Write-Host '  案例二数据库缺失，生成中…' -ForegroundColor Cyan
            & $vpy -m scripts.gen_db | Out-Null
        }
        if ($k -eq '3' -and @(Get-ChildItem 'data\contracts' -Filter *.docx -ErrorAction SilentlyContinue).Count -lt 30) {
            Write-Host '  案例三合同缺失，生成 30 份…' -ForegroundColor Cyan
            & $vpy -m scripts.gen_contracts | Out-Null
        }
    } finally { Pop-Location }
}

function Start-One([string]$k) {
    $port = Get-CasePort $k
    if (Get-Listener $port) { Write-Host ("  [跳过] {0}（{1}）已在运行" -f $cases[$k].name, $port); return $true }
    if (-not (Test-Path (Join-Path $cases[$k].dir '.env'))) {
        Write-Host ("  [失败] 缺 {0}\.env，先跑 .\scripts\setup.ps1" -f $cases[$k].dir) -ForegroundColor Red
        return $false
    }
    Ensure-Data $k
    $log = Join-Path $cases[$k].dir 'evidence\server-out.txt'
    $err = Join-Path $cases[$k].dir 'evidence\server-err.txt'
    $null = New-Item -ItemType Directory -Path (Split-Path $log) -Force
    Start-Process -FilePath $vpy -ArgumentList '-m', 'src.server' -WorkingDirectory (Join-Path $root $cases[$k].dir) `
        -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $err | Out-Null
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        if (Get-Health $port) {
            Write-Host ("  [OK]   {0} 已就绪：http://127.0.0.1:{1}" -f $cases[$k].name, $port) -ForegroundColor Green
            return $true
        }
    }
    Write-Host ("  [失败] {0} 启动超时（看 {1}）" -f $cases[$k].name, $err) -ForegroundColor Red
    return $false
}

function Stop-One([string]$k) {
    $port = Get-CasePort $k
    $l = Get-Listener $port
    if (-not $l) { Write-Host ("  [跳过] {0}（{1}）未运行" -f $cases[$k].name, $port); return $true }
    if (-not (Get-IsOurServer $l.OwningProcess)) {
        Write-Host ("  [跳过] 端口 {0} 被非本项目进程占用（PID {1}），不处理" -f $port, $l.OwningProcess) -ForegroundColor Yellow
        return $false
    }
    Stop-Process -Id $l.OwningProcess -Force
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 250
        if (-not (Get-Listener $port)) {
            Write-Host ("  [OK]   {0}（{1}）已停止" -f $cases[$k].name, $port) -ForegroundColor Green
            return $true
        }
    }
    Write-Host ("  [警告] {0} 端口仍被占用" -f $cases[$k].name) -ForegroundColor Yellow
    return $false
}

$targets = if ($Case -eq 'all') { @('1', '2', '3') } else { @($Case) }

switch ($Action) {
    'status' { Show-Status }
    'start' {
        Write-Host '== 启动 ==' -ForegroundColor Cyan
        $allOk = $true
        foreach ($k in $targets) { if (-not (Start-One $k)) { $allOk = $false } }
        Write-Host ''
        Show-Status
        if (-not $allOk) { exit 1 }
    }
    'stop' {
        Write-Host '== 停止 ==' -ForegroundColor Cyan
        $allOk = $true
        foreach ($k in $targets) { if (-not (Stop-One $k)) { $allOk = $false } }
        if (-not $allOk) { exit 1 }
    }
    'restart' {
        Write-Host '== 重启 ==' -ForegroundColor Cyan
        foreach ($k in $targets) { $null = Stop-One $k }
        Start-Sleep -Seconds 1
        $allOk = $true
        foreach ($k in $targets) { if (-not (Start-One $k)) { $allOk = $false } }
        Write-Host ''
        Show-Status
        if (-not $allOk) { exit 1 }
    }
}
