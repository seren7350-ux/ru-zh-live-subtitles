Set-StrictMode -Version Latest

function Protect-ValidationText {
    param([AllowNull()][string]$Text)

    if ($null -eq $Text) { return "" }
    $value = $Text
    $value = [regex]::Replace($value, 'hf_[A-Za-z0-9]{16,}', '<redacted-token>')
    $value = [regex]::Replace($value, '(?i)Bearer\s+\S+', 'Bearer <redacted-token>')
    $value = [regex]::Replace($value, '(?i)(HF_TOKEN|HUGGING_FACE_HUB_TOKEN)\s*[:=]\s*\S+', '$1=<redacted-token>')
    $value = [regex]::Replace($value, '(?im)^\s*(Russian(?: text)?|Chinese(?: text)?|Transcript|Translation)\s*:.*$', '$1: <redacted-caption>')
    $value = [regex]::Replace($value, '(?i)[A-Z]:\\(?:[^\s\r\n"'']+\\)*[^\s\r\n"'']*', '<redacted-path>')
    $value = [regex]::Replace($value, '(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}', '<redacted-email>')
    return $value
}

function Invoke-ValidationCommand {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = 120
    )

    $stdout = [IO.Path]::GetTempFileName()
    $stderr = [IO.Path]::GetTempFileName()
    $started = [Diagnostics.Stopwatch]::StartNew()
    try {
        $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $exited = $process.WaitForExit($TimeoutSeconds * 1000)
        if (-not $exited) {
            $process.Kill()
            $process.WaitForExit()
        }
        $started.Stop()
        $output = (Get-Content -LiteralPath $stdout -Raw -ErrorAction SilentlyContinue) + (Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue)
        [pscustomobject]@{
            name = $Name
            exit_code = if ($exited) { $process.ExitCode } else { -1 }
            timed_out = -not $exited
            duration_seconds = [math]::Round($started.Elapsed.TotalSeconds, 3)
            output = Protect-ValidationText $output
        }
    }
    finally {
        Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
    }
}

function Test-AssetManifest {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$ManifestPath,
        [switch]$ModelManifest
    )

    $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $records = if ($ModelManifest) {
        @($manifest.models | ForEach-Object { $_.files })
    }
    else {
        @($manifest.files)
    }
    $failures = [Collections.Generic.List[string]]::new()
    foreach ($record in $records) {
        if ([IO.Path]::IsPathRooted([string]$record.path)) {
            $failures.Add("absolute-manifest-path")
            continue
        }
        $path = Join-Path $Root ([string]$record.path)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $failures.Add("missing:$($record.path)")
            continue
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne ([string]$record.sha256).ToLowerInvariant()) {
            $failures.Add("hash:$($record.path)")
        }
    }
    [pscustomobject]@{
        valid = $failures.Count -eq 0
        checked_files = $records.Count
        failure_count = $failures.Count
        failures = @($failures | ForEach-Object { Protect-ValidationText $_ })
    }
}

function Get-NoNetworkEvidence {
    $interfaces = @(Get-NetAdapter -ErrorAction SilentlyContinue | Select-Object Name, Status, LinkSpeed)
    $dns = @(Get-DnsClientServerAddress -ErrorAction SilentlyContinue | Select-Object InterfaceAlias, AddressFamily, ServerAddresses)
    $routes = @(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Select-Object InterfaceAlias, NextHop, RouteMetric)
    $client = [Net.Sockets.TcpClient]::new()
    $connected = $false
    try {
        $pending = $client.ConnectAsync('1.1.1.1', 443)
        $connected = $pending.Wait(3000) -and $client.Connected
    }
    catch {
        $connected = $false
    }
    finally {
        $client.Dispose()
    }
    [pscustomobject]@{
        interfaces = $interfaces
        dns = $dns
        default_routes = $routes
        external_tcp_probe_succeeded = $connected
        hf_hub_offline = [Environment]::GetEnvironmentVariable('HF_HUB_OFFLINE')
        transformers_offline = [Environment]::GetEnvironmentVariable('TRANSFORMERS_OFFLINE')
    }
}

function Write-ValidationResult {
    param(
        [Parameter(Mandatory)][object]$Result,
        [Parameter(Mandatory)][string]$Path
    )

    $Result | Add-Member -NotePropertyName completed_at_utc -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
    $json = $Result | ConvertTo-Json -Depth 12
    $json = Protect-ValidationText $json
    [IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
}
