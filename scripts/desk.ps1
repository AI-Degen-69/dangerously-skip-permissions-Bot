<#
.SYNOPSIS
    Manager script for the Up/Down Desk Dashboard and Paper Bot API.
.DESCRIPTION
    Manages detached background processes for Vite (npm / bun run dev) on port 5173
    and the Python Desk API (python -m bot.api) on port 8789.
    Ensures port 5173 ownership, single-instance enforcement, health checks,
    and automatic browser launch.
.EXAMPLE
    desk start
    desk status
    desk restart
    desk stop
    desk logs -Tail
#>

[CmdletBinding()]
param (
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status", "logs", "open", "doctor")]
    [string]$Command = "status",

    [Parameter()]
    [switch]$Force,

    [Parameter()]
    [switch]$NoBrowser,

    [Parameter()]
    [switch]$Npm,

    [Parameter()]
    [ValidateSet("ui", "api", "all")]
    [string]$Target = "all",

    [Parameter()]
    [switch]$Tail,

    [Parameter()]
    [int]$Lines = 30
)

$ErrorActionPreference = "Stop"

# ── Bootstrap Profile Color System (PCS) ──
$colorSystemPath = "C:\Program Files\PowerShell\7\scripts\Theme\Theme-ColorSystem.ps1"
if (Test-Path $colorSystemPath) {
    . $colorSystemPath
}

if (-not (Get-Command Get-ProfileColor -ErrorAction SilentlyContinue)) {
    function Write-ProfileSuccess { param([string]$Message, [string]$Detail) Write-Host "[OK] $Message $Detail" }
    function Write-ProfileWarning { param([string]$Message, [string]$Detail) Write-Host "[!]  $Message $Detail" }
    function Write-ProfileError   { param([string]$Message, [string]$Detail, [string]$Suggestion) Write-Host "[X]  $Message $Detail $Suggestion" }
    function Write-ProfileInfo    { param([string]$Message, [string]$Detail) Write-Host "[i]  $Message $Detail" }
    function Write-ProfileNeutral { param([string]$Message, [string]$Detail) Write-Host "     $Message $Detail" }
    function Write-ProfileSection { param([string]$Title, [string]$Style) Write-Host "=== $Title ===" }
    function Write-ProfileSeparator { param([string]$Style) Write-Host "----------------------------------------" }
    function Write-ProfileKeyValue { param([string]$Key, [string]$Value, [string]$Style, [int]$KeyWidth = 16, [int]$Indent = 2) Write-Host (" " * $Indent + "$($Key.PadRight($KeyWidth)) : $Value") }
    function Get-ProfileColor     { param([string]$Name) return $null }
}

$colInfo    = Get-ProfileColor -Name Info
$colSuccess = Get-ProfileColor -Name Success
$colWarning = Get-ProfileColor -Name Warning
$colError   = Get-ProfileColor -Name Error
$colNeutral = Get-ProfileColor -Name Neutral
$colCommand = Get-ProfileColor -Name Command
$colPath    = Get-ProfileColor -Name Path

# 1. Paths & Configuration
$ProjectRoot = "C:\Users\Tiger\Agents\Projects\AI Trading\dangerously-skip-permissions-bot"
if (Test-Path (Join-Path $PSScriptRoot "..\package.json")) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$RunDir = Join-Path $ProjectRoot ".run"
if (-not (Test-Path $RunDir)) {
    New-Item -ItemType Directory -Path $RunDir -Force | Out-Null
}

$UiOutLog = Join-Path $RunDir "dashboard.log"
$UiErrLog = Join-Path $RunDir "dashboard.err.log"
$ApiOutLog = Join-Path $RunDir "api.log"
$ApiErrLog = Join-Path $RunDir "api.err.log"

$UiPidFile = Join-Path $RunDir "dashboard.pid"
$ApiPidFile = Join-Path $RunDir "api.pid"

$UI_PORT = 5173
$API_PORT = 8789
$UI_URL = "http://127.0.0.1:$UI_PORT"
$API_URL = "http://127.0.0.1:$API_PORT"

# 2. Locate Executables
$pyCmd = Get-Command python.exe -ErrorAction SilentlyContinue
$PythonExe = if ($pyCmd) { $pyCmd.Source } else { 'C:\Users\Tiger\AppData\Local\Programs\Python\Python312\python.exe' }

$bunCmd = Get-Command bun.exe -ErrorAction SilentlyContinue
$npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue

$DevExe = $null
$DevName = "npm"
if ($bunCmd -and -not $Npm) {
    $DevExe = $bunCmd.Source
    $DevName = "bun"
} elseif ($npmCmd) {
    $DevExe = $npmCmd.Source
    $DevName = "npm"
} else {
    $DevExe = 'npm.cmd'
    $DevName = "npm"
}

function Get-ChromePath {
    $candidates = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Open-DashboardBrowser {
    if ($NoBrowser) { return }
    $chrome = Get-ChromePath
    Write-ProfileInfo -Message "Opening dashboard in browser" -Detail $UI_URL
    if ($chrome) {
        Start-Process -FilePath $chrome -ArgumentList $UI_URL
    } else {
        Start-Process $UI_URL
    }
}

# 3. Port & Process Helpers
function Test-PortOccupied([int]$port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) { return $true }
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
        $listener.Start()
        $listener.Stop()
        return $false
    } catch {
        return $true
    }
}

function Get-PortProcessId([int]$port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn -and $conn.OwningProcess -gt 0) {
        return $conn.OwningProcess
    }
    return $null
}

function Test-ApiHealth {
    try {
        $resp = Invoke-RestMethod -Uri "$API_URL/api/bot/control" -TimeoutSec 2 -ErrorAction Stop
        return [PSCustomObject]@{
            Healthy  = $true
            Data     = $resp
            Strategy = "$($resp.strategy.symbol) ($($resp.strategy.id))"
            Running  = $resp.running
            RunId    = $resp.activeRunId
            LoopPid  = $resp.pid
        }
    } catch {
        return [PSCustomObject]@{
            Healthy  = $false
            Data     = $null
            Strategy = "Unavailable"
            Running  = $false
            RunId    = $null
            LoopPid  = $null
        }
    }
}

function Test-UiHealth {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$UI_PORT" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        return ($resp.StatusCode -eq 200)
    } catch {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:$UI_PORT" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            return ($resp.StatusCode -eq 200)
        } catch {
            return $false
        }
    }
}

function Spawn-DetachedProcess([string]$commandLine, [string]$workingDir) {
    try {
        $res = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
            CommandLine      = $commandLine
            CurrentDirectory = $workingDir
        }
        if ($res.ReturnValue -eq 0) {
            return $res.ProcessId
        }
    } catch {}

    $p = Start-Process -FilePath "cmd.exe" -ArgumentList "/c $commandLine" -WorkingDirectory $workingDir -WindowStyle Hidden -PassThru
    return $p.Id
}

# 4. Stop Logic
function Stop-ProcessTree([int]$parentPid) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ParentProcessId -eq $parentPid } |
        ForEach-Object { Stop-ProcessTree $_.ProcessId }

    Stop-Process -Id $parentPid -Force -ErrorAction SilentlyContinue
}

function Stop-Services {
    Write-ProfileWarning -Message "Stopping Up/Down Desk services..."
    $killedAny = $false

    $targetPids = [System.Collections.Generic.HashSet[int]]::new()

    $p5173 = Get-PortProcessId $UI_PORT
    if ($p5173) { [void]$targetPids.Add($p5173) }

    $p8789 = Get-PortProcessId $API_PORT
    if ($p8789) { [void]$targetPids.Add($p8789) }

    if (Test-Path $UiPidFile) {
        $savedPid = Get-Content $UiPidFile -ErrorAction SilentlyContinue
        if ($savedPid -match '^\d+$') { [void]$targetPids.Add([int]$savedPid) }
    }
    if (Test-Path $ApiPidFile) {
        $savedPid = Get-Content $ApiPidFile -ErrorAction SilentlyContinue
        if ($savedPid -match '^\d+$') { [void]$targetPids.Add([int]$savedPid) }
    }

    # Catch any node/vite, bun, or python instances attached to this project
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
        $cmd = $_.CommandLine
        if ($cmd) {
            $isDeskApi = ($cmd -like '*bot.api*' -or $cmd -like '*bot\api*') -and ($cmd -like "*$ProjectRoot*" -or $cmd -like "*AI Trading*")
            $isVite = ($cmd -like '*vite*' -or $cmd -like '*up-down-desk*') -and ($cmd -like "*$ProjectRoot*" -or $cmd -like "*5173*")
            if (($isDeskApi -or $isVite) -and $_.ProcessId -ne $PID) {
                [void]$targetPids.Add($_.ProcessId)
            }
        }
    }

    foreach ($pidToKill in $targetPids) {
        if (Get-Process -Id $pidToKill -ErrorAction SilentlyContinue) {
            Write-ProfileNeutral -Message "Terminating process" -Detail "PID $pidToKill"
            Stop-ProcessTree $pidToKill
            $killedAny = $true
        }
    }

    # Wait for ports to release
    $timeout = 10
    $start = Get-Date
    while ($true) {
        $uiBusy = Test-PortOccupied $UI_PORT
        $apiBusy = Test-PortOccupied $API_PORT
        if (-not $uiBusy -and -not $apiBusy) {
            break
        }
        if (((Get-Date) - $start).TotalSeconds -ge $timeout) {
            Write-ProfileWarning -Message "Timeout waiting for ports to be fully released"
            break
        }
        Start-Sleep -Milliseconds 200
    }

    Remove-Item $UiPidFile -ErrorAction SilentlyContinue
    Remove-Item $ApiPidFile -ErrorAction SilentlyContinue

    if ($killedAny) {
        Write-ProfileSuccess -Message "Services stopped and ports freed"
    } else {
        Write-ProfileNeutral -Message "No active services found to stop"
    }
}

# 5. Start Logic
function Start-Services {
    $apiHealth = Test-ApiHealth
    $uiHealth = Test-UiHealth

    # Check if healthy and running without -Force
    if (-not $Force -and $apiHealth.Healthy -and $uiHealth) {
        Write-ProfileSuccess -Message "Up/Down Desk is already running and healthy"
        Show-StatusTable
        Open-DashboardBrowser
        return
    }

    # If force or port is hung/unhealthy, clean up first
    if ($Force -or (Test-PortOccupied $UI_PORT -and -not $uiHealth) -or (Test-PortOccupied $API_PORT -and -not $apiHealth.Healthy)) {
        Write-ProfileWarning -Message "Cleaning up existing or unresponsive processes before start..."
        Stop-Services
    }

    # Start API if not healthy
    if (-not (Test-ApiHealth).Healthy) {
        Write-ProfileInfo -Message "Starting Desk API (python -m bot.api)" -Detail "port $API_PORT"
        if ((Test-Path $ApiOutLog) -and (Get-Item $ApiOutLog).Length -gt 5MB) {
            Move-Item $ApiOutLog "$ApiOutLog.old" -Force
        }

        $apiSpawnCmd = "cmd.exe /c `"`"$PythonExe`" -m bot.api >> `"$ApiOutLog`" 2>> `"$ApiErrLog`"`""
        [void](Spawn-DetachedProcess $apiSpawnCmd $ProjectRoot)

        # Wait for API to respond
        Write-Host "  -> Waiting for API on $API_URL..." -NoNewline -ForegroundColor $colNeutral
        $apiReady = $false
        $apiTimeout = 15
        $apiStart = Get-Date
        while (((Get-Date) - $apiStart).TotalSeconds -lt $apiTimeout) {
            if ((Test-ApiHealth).Healthy) {
                $apiReady = $true
                break
            }
            Write-Host "." -NoNewline -ForegroundColor $colNeutral
            Start-Sleep -Milliseconds 300
        }
        Write-Host ""

        if (-not $apiReady) {
            Write-ProfileError -Message "Desk API failed to start or respond" -Detail "URL: $API_URL" -Suggestion "Check log: $ApiErrLog"
            return
        }

        $newApiPid = Get-PortProcessId $API_PORT
        if ($newApiPid) { Set-Content -Path $ApiPidFile -Value $newApiPid }
        Write-ProfileSuccess -Message "API verified healthy on $API_URL" -Detail "PID: $newApiPid"
    } else {
        Write-ProfileNeutral -Message "Desk API already healthy on $API_URL"
    }

    # Start Dashboard on port 5173
    if (-not (Test-UiHealth)) {
        Write-ProfileInfo -Message "Starting Dashboard ($DevName run dev)" -Detail "port $UI_PORT"
        if ((Test-Path $UiOutLog) -and (Get-Item $UiOutLog).Length -gt 5MB) {
            Move-Item $UiOutLog "$UiOutLog.old" -Force
        }

        $uiSpawnCmd = "cmd.exe /c `"set `"VITE_BOT_ORIGIN=$API_URL`" && `"$DevExe`" run dev >> `"$UiOutLog`" 2>> `"$UiErrLog`"`""
        [void](Spawn-DetachedProcess $uiSpawnCmd $ProjectRoot)

        # Wait for UI to respond on port 5173
        Write-Host "  -> Waiting for Dashboard on $UI_URL..." -NoNewline -ForegroundColor $colNeutral
        $uiReady = $false
        $uiTimeout = 60
        $uiStart = Get-Date
        while (((Get-Date) - $uiStart).TotalSeconds -lt $uiTimeout) {
            if (Test-UiHealth) {
                $uiReady = $true
                break
            }
            Write-Host "." -NoNewline -ForegroundColor $colNeutral
            Start-Sleep -Milliseconds 500
        }
        Write-Host ""

        if (-not $uiReady) {
            Write-ProfileError -Message "Dashboard failed to respond" -Detail "URL: $UI_URL" -Suggestion "Check log: $UiErrLog"
            return
        }

        $newUiPid = Get-PortProcessId $UI_PORT
        if ($newUiPid) { Set-Content -Path $UiPidFile -Value $newUiPid }
        Write-ProfileSuccess -Message "Dashboard verified healthy on $UI_URL" -Detail "PID: $newUiPid"
    } else {
        Write-ProfileNeutral -Message "Dashboard already healthy on $UI_URL"
    }

    Write-Host ""
    Write-ProfileSuccess -Message "Up/Down Desk successfully started in background"
    Show-StatusTable
    Open-DashboardBrowser
}

# 6. Status Logic
function Show-StatusTable {
    $uiHealth = Test-UiHealth
    $apiHealth = Test-ApiHealth
    $uiPid = Get-PortProcessId $UI_PORT
    $apiPid = Get-PortProcessId $API_PORT

    $uiStatusText = if ($uiHealth) { "RUNNING (HTTP 200)" } elseif ($uiPid) { "UNRESPONSIVE" } else { "STOPPED" }
    $apiStatusText = if ($apiHealth.Healthy) { "RUNNING (HTTP 200)" } elseif ($apiPid) { "UNRESPONSIVE" } else { "STOPPED" }
    $botStatusText = if ($apiHealth.Running) { "RUNNING (Paper Loop)" } else { "IDLE (Run not started)" }

    $rows = @(
        [PSCustomObject]@{
            Component  = "Dashboard UI"
            Port       = $UI_PORT
            PID        = if ($uiPid) { $uiPid } else { "-" }
            Status     = $uiStatusText
            Details    = $UI_URL
        },
        [PSCustomObject]@{
            Component  = "Desk API"
            Port       = $API_PORT
            PID        = if ($apiPid) { $apiPid } else { "-" }
            Status     = $apiStatusText
            Details    = if ($apiHealth.Healthy) { "Strategy: $($apiHealth.Strategy)" } else { $API_URL }
        },
        [PSCustomObject]@{
            Component  = "Paper Bot Engine"
            Port       = "-"
            PID        = if ($apiHealth.LoopPid) { $apiHealth.LoopPid } else { "-" }
            Status     = $botStatusText
            Details    = if ($apiHealth.RunId) { "Run: $($apiHealth.RunId)" } else { "Waiting for manual start" }
        }
    )

    Write-Host ""
    Write-ProfileSection -Title "Up/Down Desk Status" -Style Info
    $rows | Format-Table -Property Component, Port, PID, Status, Details -AutoSize
}

# 7. Logs Logic
function Show-Logs {
    $filesToView = @()
    if ($Target -eq "ui" -or $Target -eq "all") {
        if (Test-Path $UiOutLog) { $filesToView += $UiOutLog }
        if (Test-Path $UiErrLog) { $filesToView += $UiErrLog }
    }
    if ($Target -eq "api" -or $Target -eq "all") {
        if (Test-Path $ApiOutLog) { $filesToView += $ApiOutLog }
        if (Test-Path $ApiErrLog) { $filesToView += $ApiErrLog }
    }

    if ($filesToView.Count -eq 0) {
        Write-ProfileNeutral -Message "No log files found in $RunDir"
        return
    }

    if ($Tail) {
        Write-ProfileInfo -Message "Streaming logs ($Target) from $RunDir" -Detail "(Ctrl+C to exit)"
        Get-Content -Path $filesToView -Tail $Lines -Wait
    } else {
        foreach ($file in $filesToView) {
            Write-Host ""
            Write-ProfileSection -Title "Log: $(Split-Path $file -Leaf) (Last $Lines lines)" -Style Info
            Get-Content -Path $file -Tail $Lines
        }
    }
}

# 8. Command Dispatch
switch ($Command.ToLower()) {
    "start" {
        Start-Services
    }
    "stop" {
        Stop-Services
    }
    "restart" {
        Write-ProfileWarning -Message "Restarting Up/Down Desk..."
        Stop-Services
        Start-Services
    }
    "status" {
        Show-StatusTable
    }
    "logs" {
        Show-Logs
    }
    "open" {
        Open-DashboardBrowser
    }
    "doctor" {
        Write-ProfileSection -Title "Up/Down Desk Doctor" -Style Info
        Show-StatusTable
        Write-Host ""
        Write-ProfileSection -Title "Environment & Origins" -Style Neutral
        Write-ProfileKeyValue -Key "Project Root" -Value $ProjectRoot -Style Info
        Write-ProfileKeyValue -Key "Python Binary" -Value $PythonExe -Style Path
        Write-ProfileKeyValue -Key "Dev Runner" -Value "$DevExe ($DevName)" -Style Info
        Write-ProfileKeyValue -Key "Chrome Found" -Value "$(Get-ChromePath)" -Style Path
        Write-ProfileKeyValue -Key "UI Log File" -Value $UiOutLog -Style Path
        Write-ProfileKeyValue -Key "API Log File" -Value $ApiOutLog -Style Path
    }
    default {
        Write-ProfileError -Message "Unknown command: $Command" -Suggestion "Usage: desk [start|stop|restart|status|logs|open|doctor]"
    }
}
