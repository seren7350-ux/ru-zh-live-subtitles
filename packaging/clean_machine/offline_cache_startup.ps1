param(
    [Parameter(Mandatory)][string]$PackageRoot,
    [Parameter(Mandatory)][string]$ResultsRoot,
    [Parameter(Mandatory)][string]$ModelRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'collect_results.ps1')

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
    actual_cuda_available = $false
    translation_device = 'cpu'
    network = $null
    process_residuals = @()
}

foreach ($name in @('python.exe', 'py.exe', 'pip.exe', 'git.exe')) {
    & where.exe $name *> $null
    $result.offline["$name`_absent"] = ($LASTEXITCODE -ne 0)
}
$result.commands += Invoke-ValidationCommand -Name 'help' -FilePath $console -Arguments @('--help')
$result.commands += Invoke-ValidationCommand -Name 'devices' -FilePath $console -Arguments @('devices')
$result.commands += Invoke-ValidationCommand -Name 'vad-doctor' -FilePath $console -Arguments @('vad-doctor')
$result.commands += Invoke-ValidationCommand -Name 'doctor' -FilePath $console -Arguments @('doctor')
$translationDoctor = Invoke-ValidationCommand -Name 'translation-doctor' -FilePath $console -Arguments @('translation-doctor')
$result.commands += $translationDoctor
$result.actual_cuda_available = $translationDoctor.output -match '(?i)CUDA available[^\r\n]*True'
$result.translation_device = if ($result.actual_cuda_available) { 'cuda' } else { 'cpu' }

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
Write-ValidationResult -Result ([pscustomobject]$result) -Path (Join-Path $ResultsRoot 'offline-cache-result.json')
