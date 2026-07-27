param(
    [Parameter(Mandatory = $true)]
    [int]$RootProcessId,
    [Parameter(Mandatory = $true)]
    [string]$Distribution,
    [Parameter(Mandatory = $true)]
    [string]$Output,
    [string]$Stage = "unspecified",
    [string]$StageFile,
    [ValidateRange(100, 250)]
    [int]$IntervalMs = 200,
    [ValidateRange(1, 600)]
    [int]$DurationSeconds = 60
)

$ErrorActionPreference = "Stop"
$distributionRoot = [System.IO.Path]::GetFullPath($Distribution).TrimEnd('\')
if (-not (Test-Path -LiteralPath $distributionRoot -PathType Container)) {
    throw "Distribution does not exist."
}

$observed = @{}
$hashCache = @{}
$permissionErrors = 0
$sampleCount = 0
$deadline = [DateTime]::UtcNow.AddSeconds($DurationSeconds)

function Get-StageName {
    if ($StageFile -and (Test-Path -LiteralPath $StageFile -PathType Leaf)) {
        $value = (Get-Content -LiteralPath $StageFile -Raw -ErrorAction SilentlyContinue).Trim()
        if ($value) { return $value }
    }
    return $Stage
}

function Get-ProcessTreeIds([int]$RootId) {
    $result = [System.Collections.Generic.HashSet[int]]::new()
    [void]$result.Add($RootId)
    $changed = $true
    while ($changed) {
        $changed = $false
        $children = Get-CimInstance Win32_Process | Where-Object { $result.Contains([int]$_.ParentProcessId) }
        foreach ($child in $children) {
            if ($result.Add([int]$child.ProcessId)) { $changed = $true }
        }
    }
    return @($result)
}

while ([DateTime]::UtcNow -lt $deadline) {
    $sampleCount += 1
    $stageName = Get-StageName
    foreach ($processId in (Get-ProcessTreeIds $RootProcessId)) {
        $role = if ($processId -eq $RootProcessId) { "parent" } else { "child" }
        try {
            $modules = Get-Process -Id $processId -Module -ErrorAction Stop
            foreach ($module in @($modules)) {
                $modulePath = $module.FileName
                $basename = [System.IO.Path]::GetFileName($modulePath)
                $isDist = $modulePath.StartsWith(
                    $distributionRoot + '\',
                    [System.StringComparison]::OrdinalIgnoreCase
                )
                if ($isDist) {
                    $relative = $modulePath.Substring($distributionRoot.Length + 1).Replace('\', '/')
                    $key = "$processId|dist|$relative"
                    if (-not $hashCache.ContainsKey($relative)) {
                        $hashCache[$relative] = (Get-FileHash -LiteralPath $modulePath -Algorithm SHA256).Hash.ToLowerInvariant()
                    }
                    $size = (Get-Item -LiteralPath $modulePath).Length
                    $sha256 = $hashCache[$relative]
                } else {
                    $relative = $null
                    $key = "$processId|system|$basename"
                    $size = $null
                    $sha256 = $null
                }
                if (-not $observed.ContainsKey($key)) {
                    $observed[$key] = [ordered]@{
                        process_id = $processId
                        process_role = $role
                        basename = $basename
                        category = if ($isDist) { "dist" } else { "system" }
                        relative_path = $relative
                        first_stage = $stageName
                        size_bytes = $size
                        sha256 = $sha256
                    }
                }
            }
        } catch {
            # A process can exit between the CIM tree snapshot and Get-Process.
            # That race is expected during normal shutdown and is not a
            # permissions failure.
            if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
                $permissionErrors += 1
            }
        }
    }
    Start-Sleep -Milliseconds $IntervalMs
}

$payload = [ordered]@{
    schema_version = 1
    interval_ms = $IntervalMs
    samples = $sampleCount
    permission_errors = $permissionErrors
    modules = @($observed.Values | Sort-Object process_id, category, relative_path, basename)
}
$outputPath = [System.IO.Path]::GetFullPath($Output)
$outputDirectory = [System.IO.Path]::GetDirectoryName($outputPath)
if ($outputDirectory) { New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null }
$json = $payload | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText(
    $outputPath,
    $json + [Environment]::NewLine,
    [System.Text.UTF8Encoding]::new($false)
)
