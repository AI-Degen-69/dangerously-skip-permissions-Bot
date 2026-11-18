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
    [Alias("Open")]
    [switch]$OpenBrowser,

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
if (Test-Path -LiteralPath $colorSystemPath) {
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

function Write-ColorHost([string]$Message, $Color, [switch]$NoNewline) {
    $params = @{ Object = $Message }
    if ($NoNewline) { $params['NoNewline'] = $true }
    if ($Color) { $params['ForegroundColor'] = $Color }
    Write-Host @params
}

# 1. Paths & Configuration
$ProjectRoot = "C:\Users\Tiger\Agents\Projects\AI Trading\dangerously-skip-permissions-bot"
$pkgPath = Join-Path $PSScriptRoot "..\package.json"
if (Test-Path -LiteralPath $pkgPath) {
    $ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

$RunDir = Join-Path $ProjectRoot ".run"
if (-not (Test-Path -LiteralPath $RunDir)) {
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
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}

function Test-DashboardBrowserConnected {
    for ($i = 0; $i -lt 3; $i++) {
        $conns = Get-NetTCPConnection -LocalPort $UI_PORT -State Established -ErrorAction SilentlyContinue
        if ($conns) {
            foreach ($c in $conns) {
                $remoteConn = Get-NetTCPConnection -LocalPort $c.RemotePort -State Established -ErrorAction SilentlyContinue | Select-Object -First 1
                $clientPid = if ($remoteConn -and $remoteConn.OwningProcess -gt 0) { $remoteConn.OwningProcess } else { $c.OwningProcess }
                $p = Get-Process -Id $clientPid -ErrorAction SilentlyContinue
                if ($p -and $p.ProcessName -in @("chrome", "msedge", "firefox", "brave", "opera", "vivaldi")) {
                    return $true
                }
            }
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Open-DashboardBrowser([switch]$ForceOpen) {
    if ($NoBrowser) { return }

    if (-not $ForceOpen -and (Test-DashboardBrowserConnected)) {
        Write-ProfileInfo -Message "Dashboard already open in browser" -Detail "Reusing active tab ($UI_URL)"
        try {
            $wshell = New-Object -ComObject WScript.Shell
            [void]$wshell.AppActivate("Up/Down Desk")
        } catch {}
        return
    }

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
        if (-not $resp -or ($null -eq $resp.strategy -and $null -eq $resp.mode -and $null -eq $resp.running)) {
            return [PSCustomObject]@{
                Healthy  = $false
                Data     = $null
                Strategy = "Invalid response"
                Running  = $false
                RunId    = $null
                LoopPid  = $null
            }
        }
        return [PSCustomObject]@{
            Healthy  = $true
            Data     = $resp
            Strategy = if ($resp.strategy) { "$($resp.strategy.symbol) ($($resp.strategy.id))" } else { "Active" }
            Running  = [bool]$resp.running
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
        if ($resp.StatusCode -eq 200 -and ($resp.Content -match '@vite/client|<title>.*Desk|src/main\.tsx|id="root"')) {
            return $true
        }
        return $false
    } catch {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:$UI_PORT" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -eq 200 -and ($resp.Content -match '@vite/client|<title>.*Desk|src/main\.tsx|id="root"')) {
                return $true
            }
            return $false
        } catch {
            return $false
        }
    }
}

function Spawn-DetachedProcess([string]$commandLine, [string]$workingDir) {
    # 1. CIM Win32_Process.Create with Win32_ProcessStartup ShowWindow = 0 (SW_HIDE)
    try {
        $cimStartupClass = Get-CimClass -ClassName Win32_ProcessStartup -ErrorAction Stop
        $cimStartup = New-CimInstance -CimClass $cimStartupClass -Property @{ ShowWindow = [uint16]0 } -ClientOnly -ErrorAction Stop
        $res = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
            CommandLine               = $commandLine
            CurrentDirectory          = $workingDir
            ProcessStartupInformation = $cimStartup
        } -ErrorAction Stop
        if ($res.ReturnValue -eq 0 -and $res.ProcessId -gt 0) {
            return [int]$res.ProcessId
        }
    } catch {}

    # 2. WMI [wmiclass] with SW_HIDE
    try {
        $wmi = [wmiclass]"win32_process"
        $startup = [wmiclass]"win32_processstartup"
        $si = $startup.CreateInstance()
        $si.ShowWindow = 0 # 0 = SW_HIDE
        $res = $wmi.Create($commandLine, $workingDir, $si)
        if ($res.ReturnValue -eq 0 -and $res.ProcessId -gt 0) {
            return [int]$res.ProcessId
        }
    } catch {}

    # 3. Fallback launch: avoid duplicate nested cmd.exe /c
    if ($commandLine -match '^cmd\.exe\s+/c\s+(.*)$') {
        $p = Start-Process -FilePath "cmd.exe" -ArgumentList "/c $($matches[1])" -WorkingDirectory $workingDir -WindowStyle Hidden -PassThru
    } else {
        $p = Start-Process -FilePath "cmd.exe" -ArgumentList "/c $commandLine" -WorkingDirectory $workingDir -WindowStyle Hidden -PassThru
    }
    return [int]$p.Id
}

# 4. Stop Logic
function Stop-ProcessTree([int]$parentPid) {
    $parentProc = Get-CimInstance Win32_Process -Filter "ProcessId = $parentPid" -ErrorAction SilentlyContinue
    $parentCreation = if ($parentProc) { $parentProc.CreationDate } else { $null }

    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ParentProcessId -eq $parentPid -and
            (-not $parentCreation -or $_.CreationDate -ge $parentCreation)
        } |
        ForEach-Object { Stop-ProcessTree $_.ProcessId }

    Stop-Process -Id $parentPid -Force -ErrorAction SilentlyContinue
}

function Stop-Services {
    Write-ProfileWarning -Message "Stopping Up/Down Desk services..."
    $killedAny = $false

    $targetPids = [System.Collections.Generic.HashSet[int]]::new()

    # Port 5173 ownership check
    $p5173 = Get-PortProcessId $UI_PORT
    if ($p5173) {
        $proc5173 = Get-CimInstance Win32_Process -Filter "ProcessId = $p5173" -ErrorAction SilentlyContinue
        if ($proc5173) {
            $cmd = $proc5173.CommandLine
            $isDeskUi = ($cmd -like "*$ProjectRoot*" -or $cmd -like "*vite*" -or $cmd -like "*up-down-desk*" -or $proc5173.Name -in @("node.exe", "bun.exe"))
            if ($isDeskUi) {
                [void]$targetPids.Add($p5173)
            } else {
                Write-ProfileWarning -Message "Port $UI_PORT occupied by external process" -Detail "PID $p5173 ($($proc5173.Name))"
            }
        }
    }

    # Port 8789 ownership check
    $p8789 = Get-PortProcessId $API_PORT
    if ($p8789) {
        $proc8789 = Get-CimInstance Win32_Process -Filter "ProcessId = $p8789" -ErrorAction SilentlyContinue
        if ($proc8789) {
            $cmd = $proc8789.CommandLine
            $isDeskApi = ($cmd -like "*$ProjectRoot*" -or $cmd -like "*bot.api*" -or $cmd -like "*bot\api*" -or $proc8789.Name -eq "python.exe")
            if ($isDeskApi) {
                [void]$targetPids.Add($p8789)
            } else {
                Write-ProfileWarning -Message "Port $API_PORT occupied by external process" -Detail "PID $p8789 ($($proc8789.Name))"
            }
        }
    }

    # Saved PID checks with validation that process belongs to desk components
    if (Test-Path -LiteralPath $UiPidFile) {
        $savedPid = Get-Content -LiteralPath $UiPidFile -ErrorAction SilentlyContinue
        if ($savedPid -match '^\d+$') {
            $sp = Get-CimInstance Win32_Process -Filter "ProcessId = $savedPid" -ErrorAction SilentlyContinue
            if ($sp -and ($sp.CommandLine -like "*$ProjectRoot*" -or $sp.CommandLine -like "*vite*" -or $sp.Name -in @("node.exe", "bun.exe", "cmd.exe"))) {
                [void]$targetPids.Add([int]$savedPid)
            }
        }
    }
    if (Test-Path -LiteralPath $ApiPidFile) {
        $savedPid = Get-Content -LiteralPath $ApiPidFile -ErrorAction SilentlyContinue
        if ($savedPid -match '^\d+$') {
            $sp = Get-CimInstance Win32_Process -Filter "ProcessId = $savedPid" -ErrorAction SilentlyContinue
            if ($sp -and ($sp.CommandLine -like "*$ProjectRoot*" -or $sp.CommandLine -like "*bot.api*" -or $sp.Name -in @("python.exe", "cmd.exe"))) {
                [void]$targetPids.Add([int]$savedPid)
            }
        }
    }

    # Catch lingering background processes strictly scoped to this project
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
        $cmd = $_.CommandLine
        if ($cmd -and $_.ProcessId -ne $PID) {
            $isDeskApi = ($cmd -like '*bot.api*' -or $cmd -like '*bot\api*') -and ($cmd -like "*$ProjectRoot*")
            $isVite = ($cmd -like '*vite*' -or $cmd -like '*up-down-desk*') -and ($cmd -like "*$ProjectRoot*")
            if ($isDeskApi -or $isVite) {
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
    $portsFreed = $true
    while ($true) {
        $uiBusy = Test-PortOccupied $UI_PORT
        $apiBusy = Test-PortOccupied $API_PORT
        if (-not $uiBusy -and -not $apiBusy) {
            break
        }
        if (((Get-Date) - $start).TotalSeconds -ge $timeout) {
            Write-ProfileError -Message "Timeout waiting for ports to be fully released" -Detail "UI busy: $uiBusy, API busy: $apiBusy" -Suggestion "Check task manager for hung processes"
            $portsFreed = $false
            break
        }
        Start-Sleep -Milliseconds 200
    }

    if ($portsFreed) {
        Remove-Item -LiteralPath $UiPidFile -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $ApiPidFile -ErrorAction SilentlyContinue
        if ($killedAny) {
            Write-ProfileSuccess -Message "Services stopped and ports freed"
        } else {
            Write-ProfileNeutral -Message "No active services found to stop"
        }
        return $true
    } else {
        return $false
    }
}

# 5. Start Logic
function Start-Services([switch]$SkipBrowser) {
    $apiHealth = Test-ApiHealth
    $uiHealth = Test-UiHealth

    # Check if healthy and running without -Force
    if (-not $Force -and $apiHealth.Healthy -and $uiHealth) {
        Write-ProfileSuccess -Message "Up/Down Desk is already running and healthy"
        Show-StatusTable
        if ($OpenBrowser) {
            Open-DashboardBrowser -ForceOpen
        }
        return $true
    }

    # If force or port is hung/unhealthy, clean up first
    if ($Force -or ((Test-PortOccupied $UI_PORT) -and -not $uiHealth) -or ((Test-PortOccupied $API_PORT) -and -not $apiHealth.Healthy)) {
        Write-ProfileWarning -Message "Cleaning up existing or unresponsive processes before start..."
        $stopOk = Stop-Services
        if (-not $stopOk) {
            Write-ProfileError -Message "Failed to stop previous services before starting new instances"
            return $false
        }
    }

    # Start API if not healthy
    if (-not (Test-ApiHealth).Healthy) {
        Write-ProfileInfo -Message "Starting Desk API (python -m bot.api)" -Detail "port $API_PORT"
        if ((Test-Path -LiteralPath $ApiOutLog) -and (Get-Item -LiteralPath $ApiOutLog).Length -gt 5MB) {
            Move-Item -LiteralPath $ApiOutLog "$ApiOutLog.old" -Force
        }

        $apiSpawnCmd = "cmd.exe /c `"`"$PythonExe`" -m bot.api >> `"$ApiOutLog`" 2>> `"$ApiErrLog`"`""
        $apiProcId = Spawn-DetachedProcess $apiSpawnCmd $ProjectRoot
        if ($apiProcId -gt 0) {
            Set-Content -LiteralPath $ApiPidFile -Value $apiProcId
        }

        # Wait for API to respond
        Write-ColorHost "  -> Waiting for API on $API_URL..." $colNeutral -NoNewline
        $apiReady = $false
        $apiTimeout = 15
        $apiStart = Get-Date
        while (((Get-Date) - $apiStart).TotalSeconds -lt $apiTimeout) {
            if ((Test-ApiHealth).Healthy) {
                $apiReady = $true
                break
            }
            Write-ColorHost "." $colNeutral -NoNewline
            Start-Sleep -Milliseconds 300
        }
        Write-Host ""

        if (-not $apiReady) {
            Write-ProfileError -Message "Desk API failed to start or respond" -Detail "URL: $API_URL" -Suggestion "Check log: $ApiErrLog"
            return $false
        }

        $newApiPid = Get-PortProcessId $API_PORT
        if ($newApiPid) { Set-Content -LiteralPath $ApiPidFile -Value $newApiPid }
        Write-ProfileSuccess -Message "API verified healthy on $API_URL" -Detail "PID: $(if ($newApiPid) { $newApiPid } else { $apiProcId })"
    } else {
        Write-ProfileNeutral -Message "Desk API already healthy on $API_URL"
    }

    # Start Dashboard on port 5173
    if (-not (Test-UiHealth)) {
        Write-ProfileInfo -Message "Starting Dashboard ($DevName run dev)" -Detail "port $UI_PORT"
        if ((Test-Path -LiteralPath $UiOutLog) -and (Get-Item -LiteralPath $UiOutLog).Length -gt 5MB) {
            Move-Item -LiteralPath $UiOutLog "$UiOutLog.old" -Force
        }

        $uiSpawnCmd = "cmd.exe /c `"set `"VITE_BOT_ORIGIN=$API_URL`" && `"$DevExe`" run dev >> `"$UiOutLog`" 2>> `"$UiErrLog`"`""
        $uiProcId = Spawn-DetachedProcess $uiSpawnCmd $ProjectRoot
        if ($uiProcId -gt 0) {
            Set-Content -LiteralPath $UiPidFile -Value $uiProcId
        }

        # Wait for UI to respond on port 5173
        Write-ColorHost "  -> Waiting for Dashboard on $UI_URL..." $colNeutral -NoNewline
        $uiReady = $false
        $uiTimeout = 60
        $uiStart = Get-Date
        while (((Get-Date) - $uiStart).TotalSeconds -lt $uiTimeout) {
            if (Test-UiHealth) {
                $uiReady = $true
                break
            }
            Write-ColorHost "." $colNeutral -NoNewline
            Start-Sleep -Milliseconds 500
        }
        Write-Host ""

        if (-not $uiReady) {
            Write-ProfileError -Message "Dashboard failed to respond" -Detail "URL: $UI_URL" -Suggestion "Check log: $UiErrLog"
            return $false
        }

        $newUiPid = Get-PortProcessId $UI_PORT
        if ($newUiPid) { Set-Content -LiteralPath $UiPidFile -Value $newUiPid }
        Write-ProfileSuccess -Message "Dashboard verified healthy on $UI_URL" -Detail "PID: $(if ($newUiPid) { $newUiPid } else { $uiProcId })"
    } else {
        Write-ProfileNeutral -Message "Dashboard already healthy on $UI_URL"
    }

    Show-StatusTable
    if (-not $SkipBrowser -and -not $NoBrowser) {
        Open-DashboardBrowser
    }
    return $true
}

# 6. Status Logic
function Show-StatusTable {
    $apiHealth = Test-ApiHealth
    $uiHealth = Test-UiHealth
    $uiPid = Get-PortProcessId $UI_PORT
    $apiPid = Get-PortProcessId $API_PORT

    $uiStatusText = if ($uiHealth) { "RUNNING (HTTP 200)" } elseif (Test-PortOccupied $UI_PORT) { "PORT BUSY (Not responding)" } else { "STOPPED" }
    $apiStatusText = if ($apiHealth.Healthy) { "RUNNING (HTTP 200)" } elseif (Test-PortOccupied $API_PORT) { "PORT BUSY (Not responding)" } else { "STOPPED" }
    $botStatusText = if ($apiHealth.Running) { "RUNNING" } else { "IDLE (Run not started)" }

    $rows = @(
        [PSCustomObject]@{
            Component  = "Dashboard UI"
            Port       = "$UI_PORT"
            PID        = if ($uiPid) { $uiPid } else { "-" }
            Status     = $uiStatusText
            Details    = $UI_URL
        },
        [PSCustomObject]@{
            Component  = "Desk API"
            Port       = "$API_PORT"
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
        if (Test-Path -LiteralPath $UiOutLog) { $filesToView += $UiOutLog }
        if (Test-Path -LiteralPath $UiErrLog) { $filesToView += $UiErrLog }
    }
    if ($Target -eq "api" -or $Target -eq "all") {
        if (Test-Path -LiteralPath $ApiOutLog) { $filesToView += $ApiOutLog }
        if (Test-Path -LiteralPath $ApiErrLog) { $filesToView += $ApiErrLog }
    }

    if ($filesToView.Count -eq 0) {
        Write-ProfileNeutral -Message "No log files found in $RunDir"
        return
    }

    if ($Tail) {
        Write-ProfileInfo -Message "Streaming logs ($Target) from $RunDir" -Detail "(Ctrl+C to exit)"
        if ($filesToView.Count -eq 1) {
            Get-Content -LiteralPath $filesToView[0] -Tail $Lines -Wait
        } else {
            foreach ($file in $filesToView) {
                Write-Host ""
                Write-ProfileSection -Title "Log: $(Split-Path $file -Leaf) (Last $Lines lines)" -Style Info
                Get-Content -LiteralPath $file -Tail $Lines
            }
            Write-Host ""
            Write-ProfileInfo -Message "Following primary log: $(Split-Path $filesToView[0] -Leaf)" -Detail "(Target single stream via -Target ui or -Target api)"
            Get-Content -LiteralPath $filesToView[0] -Tail 10 -Wait
        }
    } else {
        foreach ($file in $filesToView) {
            Write-Host ""
            Write-ProfileSection -Title "Log: $(Split-Path $file -Leaf) (Last $Lines lines)" -Style Info
            Get-Content -LiteralPath $file -Tail $Lines
        }
    }
}

# 8. Command Dispatch
switch ($Command.ToLower()) {
    "start" {
        $ok = Start-Services
        if (-not $ok) { exit 1 }
    }
    "stop" {
        $ok = Stop-Services
        if (-not $ok) { exit 1 }
    }
    "restart" {
        Write-ProfileWarning -Message "Restarting Up/Down Desk..."
        $wasRunning = (Test-PortOccupied $UI_PORT) -or (Test-PortOccupied $API_PORT)
        $stopOk = Stop-Services
        if (-not $stopOk) { exit 1 }

        # If services were already running, existing browser tab will auto-refresh via Vite.
        # Skip opening duplicate tab unless user explicitly passed -OpenBrowser / -Open.
        $skip = $wasRunning -and -not $OpenBrowser
        $startOk = Start-Services -SkipBrowser:$skip
        if (-not $startOk) { exit 1 }
        if ($skip) {
            Write-ProfileInfo -Message "Existing browser tab retained" -Detail "Vite will auto-refresh at $UI_URL"
        }
    }
    "status" {
        Show-StatusTable
    }
    "logs" {
        Show-Logs
    }
    "open" {
        Open-DashboardBrowser -ForceOpen
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
        exit 1
    }
}
