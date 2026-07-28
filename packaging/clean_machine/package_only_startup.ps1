param(
    [Parameter(Mandatory)][string]$PackageRoot,
    [Parameter(Mandatory)][string]$ResultsRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'collect_results.ps1')

$console = Join-Path $PackageRoot 'ru-zh-subtitles-console.exe'
$gui = Join-Path $PackageRoot 'ru-zh-subtitles.exe'
$result = [ordered]@{
    schema_version = 1
    phase = 'package-only'
    clean_environment = [ordered]@{}
    commands = @()
    package_manifest = $null
    package_read_only = $false
    network = $null
    defender = $null
    process_residuals = @()
    warnings = @()
}

foreach ($name in @('python.exe', 'py.exe', 'pip.exe', 'git.exe')) {
    $command = Get-Command -Name $name -CommandType Application -ErrorAction SilentlyContinue
    $result.clean_environment[$name] = ($null -eq $command)
}
$result.clean_environment['project_source_absent'] = -not (Test-Path 'C:\Users\WDAGUtilityAccount\ru-zh-live-subtitles')
$result.clean_environment['venv_absent'] = -not (Test-Path 'C:\Validation\.venv')
$result.clean_environment['packaging_venv_absent'] = -not (Test-Path 'C:\Validation\.venv-packaging')
$result.clean_environment['huggingface_cache_absent'] = -not (Test-Path "$env:USERPROFILE\.cache\huggingface")
$result.clean_environment['silero_cache_absent'] = -not (Test-Path "$env:LOCALAPPDATA\ru-zh-live-subtitles\models\silero-vad")

$result.package_manifest = Test-AssetManifest -Root $PackageRoot -ManifestPath (Join-Path $PackageRoot 'asset-manifest.json')
$result.commands += Invoke-ValidationCommand -Name 'help' -FilePath $console -Arguments @('--help')
$result.commands += Invoke-ValidationCommand -Name 'devices' -FilePath $console -Arguments @('devices')
$result.commands += Invoke-ValidationCommand -Name 'vad-doctor-missing-cache' -FilePath $console -Arguments @('vad-doctor')
$result.commands += Invoke-ValidationCommand -Name 'doctor-missing-cache' -FilePath $console -Arguments @('doctor')
$result.commands += Invoke-ValidationCommand -Name 'translation-doctor-missing-cache' -FilePath $console -Arguments @('translation-doctor')

$probe = Join-Path $PackageRoot '.read-only-probe'
try {
    [IO.File]::WriteAllText($probe, 'must fail')
    $result.package_read_only = $false
    $result.warnings += 'Package mapping unexpectedly accepted a write probe.'
}
catch {
    $result.package_read_only = $true
}

$result.commands += Invoke-ValidationCommand -Name 'overlay-demo' -FilePath $gui -Arguments @('overlay-demo', '--duration', '5') -TimeoutSeconds 20
$result.commands += Invoke-ValidationCommand -Name 'live-overlay-missing-cache' -FilePath $console -Arguments @('live-overlay', '--duration', '5', '--auto-start') -TimeoutSeconds 20
$defenderCandidates = @(
    (Join-Path $env:ProgramFiles 'Windows Defender\MpCmdRun.exe'),
    (Join-Path $env:ProgramData 'Microsoft\Windows Defender\Platform')
)
$defender = $defenderCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($defender -and (Get-Item -LiteralPath $defender).PSIsContainer) {
    $defender = Get-ChildItem -LiteralPath $defender -Directory | Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName 'MpCmdRun.exe' } | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if ($defender) {
    $result.defender = Invoke-ValidationCommand -Name 'defender-package-scan' -FilePath $defender -Arguments @('-Scan', '-ScanType', '3', '-File', $PackageRoot) -TimeoutSeconds 600
}
else {
    $result.defender = [pscustomobject]@{ available = $false; status = 'MpCmdRun.exe unavailable' }
}
$result.network = Get-NoNetworkEvidence
$result.process_residuals = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'ru-zh-subtitles*' } | Select-Object ProcessName, Id)

$logRoot = Join-Path $env:LOCALAPPDATA 'ru-zh-live-subtitles\logs'
if (Test-Path $logRoot) {
    $logText = Get-ChildItem $logRoot -File | ForEach-Object { Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue }
    $redacted = Protect-ValidationText ($logText -join "`n")
    $result.log_privacy = [ordered]@{
        token_marker = $redacted -match 'hf_[A-Za-z0-9]{16,}|Bearer\s+\S+'
        caption_marker = $redacted -match '(?im)^\s*(Russian|Chinese|Transcript|Translation)\s*:'
        host_path_marker = $redacted -match '(?i)C:\\Users\\(?!WDAGUtilityAccount)'
    }
}

Write-ValidationResult -Result ([pscustomobject]$result) -Path (Join-Path $ResultsRoot 'package-only-result.json')
