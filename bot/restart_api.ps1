# Determine project root dynamically from the script directory
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# Find Python executable
$pyCmd = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pyCmd) {
    $PythonExe = $pyCmd.Source
} else {
    $PythonExe = 'C:\Users\Tiger\AppData\Local\Programs\Python\Python312\python.exe'
}

# 1. Find any running processes serving bot/api.py or holding port 8789
$targetPids = [System.Collections.Generic.HashSet[int]]::new()

# Look by CommandLine
Get-CimInstance Win32_Process | ForEach-Object {
    if ($_.CommandLine -and ($_.CommandLine -like '*bot/api.py*' -or $_.CommandLine -like '*bot\api.py*')) {
        [void]$targetPids.Add($_.ProcessId)
    }
}

# Also inspect port 8789 listeners
Get-NetTCPConnection -LocalPort 8789 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.OwningProcess -gt 0) {
        [void]$targetPids.Add($_.OwningProcess)
    }
}

if ($targetPids.Count -gt 0) {
    Write-Host "Stopping existing bot/api.py process(es)..."
    foreach ($pidToKill in $targetPids) {
        Write-Host "  -> Killing PID $pidToKill..."
        Stop-Process -Id $pidToKill -Force -ErrorAction SilentlyContinue
    }

    # 2. Strict verification loop: confirm processes and port are freed
    $timeoutSeconds = 10
    $startTime = Get-Date

    while ($true) {
        $stillAlive = $false
        foreach ($pidToKill in $targetPids) {
            if (Get-Process -Id $pidToKill -ErrorAction SilentlyContinue) {
                $stillAlive = $true
                break
            }
        }

        $portOccupied = Get-NetTCPConnection -LocalPort 8789 -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -gt 0 }

        if (-not $stillAlive -and -not $portOccupied) {
            Write-Host "Verified: previous instance terminated and port 8789 released."
            break
        }

        if (((Get-Date) - $startTime).TotalSeconds -ge $timeoutSeconds) {
            Write-Error "Timed out waiting for existing bot/api.py process (or port 8789) to terminate."
            exit 1
        }

        Start-Sleep -Milliseconds 250
    }
} else {
    Write-Host "No existing bot/api.py processes found."
}

# 3. Start a new background instance in the current repository
Write-Host "Starting bot/api.py in background from $ProjectRoot..."
Start-Process -FilePath $PythonExe -ArgumentList 'bot/api.py' -WorkingDirectory $ProjectRoot -WindowStyle Hidden

# 4. Verification loop: ensure the new instance has bound the port and is responding
$verifyStart = Get-Date
$apiUp = $false

while (((Get-Date) - $verifyStart).TotalSeconds -lt 5) {
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8789/api/bot/control" -TimeoutSec 1 -ErrorAction Stop
        if ($resp) {
            $apiUp = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 300
    }
}

if ($apiUp) {
    Write-Host "Success: bot/api.py is running and responding on http://127.0.0.1:8789"
} else {
    Write-Warning "Started process, but endpoint http://127.0.0.1:8789 did not respond within 5 seconds."
}
