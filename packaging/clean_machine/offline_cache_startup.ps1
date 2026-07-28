param(
    [Parameter(Mandatory)][string]$PackageRoot,
    [Parameter(Mandatory)][string]$ResultsRoot,
    [Parameter(Mandatory)][string]$ModelRoot,
    [ValidateSet('any', 'cpu', 'gpu')][string]$ExpectedRuntimeFamily = 'any'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'collect_results.ps1')

function Get-DiagnosticDetail {
    param([Parameter(Mandatory)][string]$Output, [Parameter(Mandatory)][string]$Name)
    $escaped = [regex]::Escape($Name)
    $match = [regex]::Match($Output, "(?m)^\[(?:OK|WARN|FAIL)\]\s+${escaped}:\s*(.+?)\s*$")
    if ($match.Success) { return $match.Groups[1].Value.Trim() }
    return 'unavailable'
}

$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$cacheRoot = Join-Path $env:LOCALAPPDATA 'ru-zh-live-subtitles\sandbox-cache'
$hfHome = Join-Path $cacheRoot 'hf-home'
$sileroTarget = Join-Path $env:LOCALAPPDATA 'ru-zh-live-subtitles\models\silero-vad\6.2.1'
New-Item -ItemType Directory -Force -Path $cacheRoot, $hfHome, $sileroTarget | Out-Null
$copyTimer = [Diagnostics.Stopwatch]::StartNew()
Copy-Item -LiteralPath (Join-Path $ModelRoot 'hf-home\hub') -Destination $hfHome -Recurse -Force
Copy-Item -Path (Join-Path $ModelRoot 'silero-vad\6.2.1\*') -Destination $sileroTarget -Force
$copyTimer.Stop()
$env:HF_HOME = $hfHome

$console = Join-Path $PackageRoot 'ru-zh-subtitles-console.exe'
$result = [ordered]@{
    schema_version = 1
    phase = 'offline-cache'
    offline = [ordered]@{
        hf_hub_offline = $env:HF_HUB_OFFLINE
        transformers_offline = $env:TRANSFORMERS_OFFLINE
        cache_copy_seconds = [math]::Round($copyTimer.Elapsed.TotalSeconds, 3)
    }
    package_manifest = Test-AssetManifest -Root $PackageRoot -ManifestPath (Join-Path $PackageRoot 'asset-manifest.json')
    model_manifest = Test-AssetManifest -Root $ModelRoot -ManifestPath (Join-Path $ModelRoot 'model-manifest.json') -ModelManifest
    commands = @()
    command_failures = @()
    actual_cuda_available = $false
    translation_device = 'cpu'
    runtime = [ordered]@{
        expected_family = $ExpectedRuntimeFamily
        package_runtime_family = 'unavailable'
        torch_version = 'unavailable'
        torch_cuda_version = 'unavailable'
        cuda_available = 'unavailable'
        selected_translation_device = 'unavailable'
        frozen_state = 'unavailable'
        boundary_valid = $false
    }
    network = $null
    process_residuals = @()
}

foreach ($name in @('python.exe', 'py.exe', 'pip.exe', 'git.exe')) {
    $command = Get-Command -Name $name -CommandType Application -ErrorAction SilentlyContinue
    $result.offline["$name`_absent"] = ($null -eq $command)
}
$result.commands += Invoke-ValidationCommand -Name 'help' -FilePath $console -Arguments @('--help')
$result.commands += Invoke-ValidationCommand -Name 'devices' -FilePath $console -Arguments @('devices')
$result.commands += Invoke-ValidationCommand -Name 'vad-doctor' -FilePath $console -Arguments @('vad-doctor')
$result.commands += Invoke-ValidationCommand -Name 'doctor' -FilePath $console -Arguments @('doctor')
$translationDoctor = Invoke-ValidationCommand -Name 'translation-doctor' -FilePath $console -Arguments @('translation-doctor')
$result.commands += $translationDoctor
$result.runtime.package_runtime_family = Get-DiagnosticDetail -Output $translationDoctor.output -Name 'Package runtime family'
$result.runtime.torch_version = Get-DiagnosticDetail -Output $translationDoctor.output -Name 'torch'
$result.runtime.torch_cuda_version = Get-DiagnosticDetail -Output $translationDoctor.output -Name 'Torch CUDA version'
$result.runtime.cuda_available = Get-DiagnosticDetail -Output $translationDoctor.output -Name 'CUDA available'
$result.runtime.selected_translation_device = Get-DiagnosticDetail -Output $translationDoctor.output -Name 'Selected translation device'
$result.runtime.frozen_state = Get-DiagnosticDetail -Output $translationDoctor.output -Name 'Frozen state'
$result.actual_cuda_available = $result.runtime.cuda_available -eq 'True'
$result.translation_device = $result.runtime.selected_translation_device
$result.runtime.boundary_valid = (
    $result.translation_device -in @('cpu', 'cuda') -and
    ($ExpectedRuntimeFamily -eq 'any' -or $result.runtime.package_runtime_family -eq $ExpectedRuntimeFamily)
)
if ($ExpectedRuntimeFamily -eq 'cpu') {
    $result.runtime.boundary_valid = (
        $result.runtime.boundary_valid -and
        $result.runtime.torch_cuda_version -eq 'None' -and
        $result.runtime.cuda_available -eq 'False' -and
        $result.runtime.selected_translation_device -eq 'cpu' -and
        $result.runtime.frozen_state -eq 'True'
    )
}
if (-not $result.runtime.boundary_valid) {
    $result.network = Get-NoNetworkEvidence
    $result.process_residuals = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'ru-zh-subtitles*' } | Select-Object ProcessName, Id)
    Write-ValidationResult -Result ([pscustomobject]$result) -Path (Join-Path $ResultsRoot 'offline-cache-result.json')
    throw 'Package runtime boundary validation failed; model loading was not attempted.'
}

$testAudio = Join-Path $PSScriptRoot 'test-audio\sample.wav'
if (Test-Path -LiteralPath $testAudio -PathType Leaf) {
    $audioManifestPath = Join-Path $PSScriptRoot 'test-audio-manifest.json'
    if (-not (Test-Path -LiteralPath $audioManifestPath -PathType Leaf)) {
        throw 'Staged test audio has no manifest.'
    }
    $result.test_audio_manifest = Test-AssetManifest -Root $PSScriptRoot -ManifestPath $audioManifestPath
    if (-not $result.test_audio_manifest.valid) {
        throw 'Staged test audio failed manifest validation.'
    }
    $result.commands += Invoke-ValidationCommand -Name 'transcribe-file' -FilePath $console -Arguments @('transcribe-file', $testAudio) -TimeoutSeconds 300
    $result.commands += Invoke-ValidationCommand -Name 'translate-audio' -FilePath $console -Arguments @('translate-audio', $testAudio, '--translation-engine', 'nllb', '--device', $result.translation_device) -TimeoutSeconds 600
}
else {
    $result.offline['file_pipeline_skipped'] = 'No local non-sensitive staged WAV was supplied.'
}

$result.network = Get-NoNetworkEvidence
$result.process_residuals = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'ru-zh-subtitles*' } | Select-Object ProcessName, Id)
$result.command_failures = @(
    $result.commands | Where-Object { $_.timed_out -or $_.exit_code -ne 0 } |
        Select-Object name, exit_code, timed_out
)
Write-ValidationResult -Result ([pscustomobject]$result) -Path (Join-Path $ResultsRoot 'offline-cache-result.json')
if ($result.command_failures.Count -gt 0) {
    throw "Offline validation command failure(s): $($result.command_failures.name -join ', ')"
}
