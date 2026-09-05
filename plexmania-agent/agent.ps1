# AT Network Dashboard - plexmania process-control agent.
#
# No Docker on this host: Plex, ErsatzTV and NeXroll run as bare Windows
# processes (only PlexUpdateService and a stopped NeXrollService are
# registered services - not the actual running apps), so this mirrors
# docker-agent's shape (status + restart, shared-token auth) using plain
# process kill+relaunch instead of container start/stop/restart.
#
# Run elevated (Task Scheduler, "Run with highest privileges", trigger "At
# log on" for adamt) - HttpListener needs elevation or a URL ACL reservation
# to bind 0.0.0.0, since the main dashboard reaches this over the LAN.

$ErrorActionPreference = 'Stop'
$Port = 8299
$TokenPath = Join-Path $PSScriptRoot 'token.txt'
$AgentToken = (Get-Content $TokenPath -Raw).Trim()

$Apps = @{
    plex = @{
        ProcessNames = @('Plex Media Server')
        ExePath      = 'C:\Program Files\Plex\Plex Media Server\Plex Media Server.exe'
        Port         = 32400
    }
    ersatztv = @{
        ProcessNames = @('ErsatzTV', 'ErsatzTV-Windows')
        ExePath      = 'C:\Users\adamt\Desktop\ersatztv\ErsatzTV.exe'
        Port         = 8409
    }
    nexroll = @{
        ProcessNames = @('NeXroll', 'NeXrollTray')
        ExePath      = 'C:\Program Files\NeXroll\NeXroll.exe'
        Port         = 9393
    }
}

function Test-PortOpen {
    param([int]$Port, [int]$TimeoutMs = 1500)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $result = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        $ok = $result.AsyncWaitHandle.WaitOne($TimeoutMs)
        if ($ok -and $client.Connected) { $client.Close(); return $true }
        $client.Close()
        return $false
    } catch { return $false }
}

function Get-AppStatus {
    param([string]$Name)
    $app = $Apps[$Name]
    $running = @(Get-Process -Name $app.ProcessNames -ErrorAction SilentlyContinue)
    [ordered]@{
        name        = $Name
        running     = $running.Count -gt 0
        process_count = $running.Count
        port_open   = Test-PortOpen -Port $app.Port
    }
}

function Restart-App {
    param([string]$Name)
    $app = $Apps[$Name]
    Get-Process -Name $app.ProcessNames -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
    Start-Process -FilePath $app.ExePath
    # Give it a moment, then report whether the port actually came back -
    # a real signal the app is functioning, not just that a process exists.
    $upBy = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        if (Test-PortOpen -Port $app.Port) { $upBy = $true; break }
    }
    [ordered]@{ ok = $true; port_responding_after_restart = $upBy }
}

function Write-JsonResponse {
    param($Context, $StatusCode, $Body)
    $Context.Response.StatusCode = $StatusCode
    $Context.Response.ContentType = 'application/json'
    $json = $Body | ConvertTo-Json -Depth 5 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $Context.Response.ContentLength64 = $bytes.Length
    $Context.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    $Context.Response.OutputStream.Close()
}

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://+:$Port/")
$listener.Start()
Write-Output "plexmania-agent listening on port $Port"

while ($listener.IsListening) {
    $context = $listener.GetContext()
    try {
        $token = $context.Request.Headers['X-Agent-Token']
        if (-not $token -or $token -ne $AgentToken) {
            Write-JsonResponse $context 401 @{ detail = 'Invalid or missing agent token' }
            continue
        }

        $path = $context.Request.Url.AbsolutePath
        $method = $context.Request.HttpMethod

        if ($method -eq 'GET' -and $path -eq '/processes') {
            $statuses = @($Apps.Keys | ForEach-Object { Get-AppStatus -Name $_ })
            Write-JsonResponse $context 200 @{ host = 'plexmania'; processes = $statuses }
        }
        elseif ($method -eq 'POST' -and $path -match '^/processes/([a-z]+)/restart$') {
            $name = $Matches[1]
            if (-not $Apps.ContainsKey($name)) {
                Write-JsonResponse $context 404 @{ detail = "Unknown app: $name" }
            } else {
                $result = Restart-App -Name $name
                Write-JsonResponse $context 200 $result
            }
        }
        elseif ($method -eq 'GET' -and $path -eq '/health') {
            Write-JsonResponse $context 200 @{ status = 'ok'; host = 'plexmania' }
        }
        else {
            Write-JsonResponse $context 404 @{ detail = 'Not found' }
        }
    } catch {
        try { Write-JsonResponse $context 500 @{ detail = $_.Exception.Message } } catch {}
    }
}
