# AT Network Dashboard - plexmania process-control agent.
#
# No Docker on this host: Plex, ErsatzTV and NeXroll run as bare Windows
# processes (only PlexUpdateService and a stopped NeXrollService are
# registered services - not the actual running apps), so this mirrors
# docker-agent's shape (status + restart, shared-token auth) using plain
# process kill+relaunch instead of container start/stop/restart.
#
# Run elevated (Task Scheduler, "Run with highest privileges") - HttpListener
# needs elevation or a URL ACL reservation to bind 0.0.0.0, since the main
# dashboard reaches this over the LAN. Use trigger "At startup" with "Run
# whether user is logged on or not", not "At log on" - the latter means this
# never comes back after a reboot with no interactive session, which is what
# caused the outage this agent.ps1 revision exists to make less likely to
# recur (also add a "restart on failure" action so a crash self-heals).

$ErrorActionPreference = 'Stop'
$Port = 8299
$TokenPath = Join-Path $PSScriptRoot 'token.txt'
$AgentToken = (Get-Content $TokenPath -Raw).Trim()

function Test-TokenMatch {
    # Plain string -eq/-ne on the raw token would leak how many leading bytes
    # matched via response timing (a classic side-channel on network-exposed
    # auth checks - the Linux agents avoid this with hmac.compare_digest).
    # Hashing both sides first normalises to a fixed 32-byte length so there's
    # nothing to leak from length either, then the compare loop always visits
    # every byte regardless of where the first mismatch is.
    param([string]$Provided, [string]$Expected)
    if ([string]::IsNullOrEmpty($Provided)) { return $false }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $providedHash = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Provided))
        $expectedHash = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Expected))
    } finally {
        $sha.Dispose()
    }
    $diff = 0
    for ($i = 0; $i -lt $providedHash.Length; $i++) { $diff = $diff -bor ($providedHash[$i] -bxor $expectedHash[$i]) }
    return $diff -eq 0
}

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

# Commands matching any of these are refused outright, regardless of who or
# what asked for them - same philosophy as the Linux shell-agent's denylist
# (app/shell_agent/app.py): things with no legitimate "fix an incident" use
# case and a catastrophic, usually irreversible blast radius. Everything else
# is allowed to run - the caller logs every command/output as the safety net.
$DenylistPatterns = @(
    'Format-Volume',
    'Clear-Disk',
    '\bdiskpart\b',
    '\bsdelete\b',
    'cipher\s+/w',
    'Stop-Computer',
    'Restart-Computer',
    'shutdown(\.exe)?\s+/[rs]\b',
    'Set-MpPreference\s+.*-DisableRealtimeMonitoring',
    'netsh\s+advfirewall\s+set\s+allprofiles\s+state\s+off',
    'reg(\.exe)?\s+delete\s+HKLM\\SAM',
    'net(\.exe)?\s+user\s+administrator',
    '(iwr|Invoke-WebRequest)\b.*\|\s*(iex|Invoke-Expression)\b',
    'wevtutil\s+cl\b',
    'vssadmin\s+delete\s+shadows'
)

# A single "flags-then-path" regex only catches one exact spelling and misses
# equally-valid equivalents, since PowerShell parameters can come before or
# after the path (e.g. "Remove-Item C:\ -Recurse" vs "-Recurse C:\"). Check
# root-targeting and -Recurse independently so order doesn't matter.
$RootTargetRemoveItem = 'Remove-Item\b[^\n;]*?(?:^|\s)[A-Za-z]:\\?(?:\s|;|$)'
$RecurseFlag = '-Recurse\b'

function Test-CommandBlocked {
    param([string]$Command)
    if (($Command -imatch $RootTargetRemoveItem) -and ($Command -imatch $RecurseFlag)) {
        return "Command blocked by safety denylist (Remove-Item -Recurse targeting a drive root, regardless of parameter order)"
    }
    foreach ($pattern in $DenylistPatterns) {
        if ($Command -imatch $pattern) {
            return "Command blocked by safety denylist (matched pattern: $pattern)"
        }
    }
    return $null
}

function Invoke-AgentCommand {
    param([string]$Command, [int]$TimeoutSeconds = 30)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'powershell.exe'
    $psi.Arguments = '-NoProfile -NonInteractive -Command -'
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $proc = [System.Diagnostics.Process]::Start($psi)
    $proc.StandardInput.Write($Command)
    $proc.StandardInput.Close()
    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()
    $completed = $proc.WaitForExit($TimeoutSeconds * 1000)
    if (-not $completed) {
        try { $proc.Kill() } catch {}
        return [ordered]@{ ok = $false; blocked = $false; command = $Command; message = "Command timed out after $TimeoutSeconds s" }
    }
    $stdout = $stdoutTask.Result
    $stderr = $stderrTask.Result
    [ordered]@{
        ok        = ($proc.ExitCode -eq 0)
        blocked   = $false
        command   = $Command
        exit_code = $proc.ExitCode
        stdout    = $stdout.Substring(0, [Math]::Min(8000, $stdout.Length))
        stderr    = $stderr.Substring(0, [Math]::Min(4000, $stderr.Length))
    }
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
        if (-not (Test-TokenMatch -Provided $token -Expected $AgentToken)) {
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
        elseif ($method -eq 'POST' -and $path -eq '/exec') {
            $reader = New-Object System.IO.StreamReader($context.Request.InputStream)
            $bodyText = $reader.ReadToEnd()
            $reader.Close()
            $bodyObj = $null
            try { $bodyObj = $bodyText | ConvertFrom-Json } catch {}
            $command = if ($bodyObj) { [string]$bodyObj.command } else { '' }
            $timeoutSec = if ($bodyObj -and $bodyObj.timeout) { [int]$bodyObj.timeout } else { 30 }
            if ($timeoutSec -lt 1) { $timeoutSec = 1 }
            if ($timeoutSec -gt 120) { $timeoutSec = 120 }

            if ([string]::IsNullOrWhiteSpace($command)) {
                Write-JsonResponse $context 400 @{ detail = 'Empty command' }
            } else {
                $blockedReason = Test-CommandBlocked -Command $command
                if ($blockedReason) {
                    Write-JsonResponse $context 200 @{ ok = $false; blocked = $true; message = $blockedReason; command = $command }
                } else {
                    $result = Invoke-AgentCommand -Command $command -TimeoutSeconds $timeoutSec
                    Write-JsonResponse $context 200 $result
                }
            }
        }
        else {
            Write-JsonResponse $context 404 @{ detail = 'Not found' }
        }
    } catch {
        try { Write-JsonResponse $context 500 @{ detail = $_.Exception.Message } } catch {}
    }
}
