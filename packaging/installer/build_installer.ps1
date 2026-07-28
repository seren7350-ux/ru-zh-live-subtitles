[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$RepoRoot,
    [Parameter(Mandatory = $false)]
    [string]$CpuDist,
    [Parameter(Mandatory = $false)]
    [string]$OutputDir,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedCommit,
    [Parameter(Mandatory = $false)]
    [string]$IsccPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}

function Resolve-ExistingDirectory([string]$Path, [string]$Label) {
    $resolved = Resolve-Path -LiteralPath $Path -ErrorAction SilentlyContinue
    if ($null -eq $resolved -or -not (Test-Path -LiteralPath $resolved.Path -PathType Container)) {
        throw "$Label does not exist: $Path"
    }
    return $resolved.Path
}

function Find-Iscc([string]$RequestedPath) {
    $candidates = @()
    if ($RequestedPath) { $candidates += $RequestedPath }
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($null -ne $command) { $candidates += $command.Source }
    $candidates += @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 7\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 7\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 7\ISCC.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw 'ISCC.exe was not found. Install the official Inno Setup 7.0.2 x64 release.'
}

function Get-IsccVersion([string]$CompilerPath) {
    $compiler = [IO.Path]::GetFullPath($CompilerPath)
    $entries = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' |
        Where-Object { $_.DisplayName -like 'Inno Setup 7*' -and $_.InstallLocation }
    foreach ($entry in $entries) {
        $location = [IO.Path]::GetFullPath([string]$entry.InstallLocation)
        if ($compiler.StartsWith($location, [StringComparison]::OrdinalIgnoreCase)) {
            return [string]$entry.DisplayVersion
        }
    }
    throw 'Unable to determine the installed Inno Setup version.'
}

$started = [Diagnostics.Stopwatch]::StartNew()
$repo = Resolve-ExistingDirectory $RepoRoot 'Repository root'
if (-not $CpuDist) { $CpuDist = Join-Path $repo 'dist\ru-zh-subtitles-cpu' }
if (-not $OutputDir) { $OutputDir = Join-Path $repo 'dist\installer' }
$cpu = Resolve-ExistingDirectory $CpuDist 'CPU distribution'
$output = [IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $output | Out-Null

$status = & git -C $repo status --porcelain=v1
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect the Git working tree.' }
$head = (& git -C $repo rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Unable to read the Git commit.' }
if ($head -ne $ExpectedCommit) {
    throw "Git commit mismatch: expected $ExpectedCommit, found $head."
}

$python = Join-Path $repo '.venv-packaging-cpu\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "CPU packaging Python is missing: $python"
}
$validator = Join-Path $repo 'packaging\validate_cpu_distribution.py'
$metadataTool = Join-Path $repo 'packaging\installer\release_metadata.py'
$iss = Join-Path $repo 'packaging\installer\cpu-only.iss'

$iscc = Find-Iscc $IsccPath
$signature = Get-AuthenticodeSignature -LiteralPath $iscc
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Pyrsys B\.V\.') {
    throw 'ISCC.exe does not have the required valid Pyrsys B.V. Authenticode signature.'
}
$innoVersion = Get-IsccVersion $iscc
if ($innoVersion -ne '7.0.2') { throw "Inno Setup 7.0.2 is required; found $innoVersion." }

$temporary = Join-Path $output ('.build-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
$policyJson = Join-Path $temporary 'cpu-policy.json'
$releaseMetadata = Join-Path $temporary 'RELEASE_METADATA.json'

& $python $validator $cpu --json-output $policyJson | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'CPU distribution policy validation failed.' }

$oldHubOffline = $env:HF_HUB_OFFLINE
$oldTransformersOffline = $env:TRANSFORMERS_OFFLINE
try {
    $env:HF_HUB_OFFLINE = '1'
    $env:TRANSFORMERS_OFFLINE = '1'
    $doctorOutput = & (Join-Path $cpu 'ru-zh-subtitles-console.exe') translation-doctor 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Frozen CPU translation-doctor failed.' }
} finally {
    if ($null -eq $oldHubOffline) { Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue } else { $env:HF_HUB_OFFLINE = $oldHubOffline }
    if ($null -eq $oldTransformersOffline) { Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue } else { $env:TRANSFORMERS_OFFLINE = $oldTransformersOffline }
}
$doctorText = $doctorOutput -join "`n"
foreach ($required in @('Package runtime family: cpu', 'Torch CUDA version: None', 'CUDA available: False', 'Selected translation device: cpu')) {
    if ($doctorText -notmatch [regex]::Escape($required)) {
        throw "Frozen CPU runtime check is missing: $required"
    }
}

$version = (& $python $metadataTool --repo-root $repo --version-only).Trim()
if ($LASTEXITCODE -ne 0 -or -not $version) { throw 'Unable to read the application version.' }
& $python $metadataTool --repo-root $repo --cpu-dist $cpu --expected-commit $ExpectedCommit --inno-version $innoVersion --output $releaseMetadata --full-manifest | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Release metadata generation failed.' }

$baseName = "ru-zh-live-subtitles-cpu-$version-setup"
$arguments = @(
    '/Qp',
    "/O$temporary",
    "/F$baseName",
    "/DAppVersion=$version",
    "/DVersionInfoVersion=$version.0",
    "/DCpuDist=$cpu",
    "/DRepoRoot=$repo",
    "/DReleaseMetadata=$releaseMetadata",
    $iss
)
$compilerOutput = @(& $iscc @arguments 2>&1)
$compilerExitCode = $LASTEXITCODE
$compilerLog = Join-Path $temporary 'iscc.log'
Set-Content -LiteralPath $compilerLog -Value $compilerOutput -Encoding utf8
if ($compilerExitCode -ne 0) {
    throw "Inno Setup compilation failed with exit code $compilerExitCode. See $compilerLog"
}
$compilerWarnings = @($compilerOutput | Where-Object { [string]$_ -match '(?i)\bwarning\b' })

$compiled = Join-Path $temporary "$baseName.exe"
if (-not (Test-Path -LiteralPath $compiled -PathType Leaf)) {
    throw "Inno Setup did not produce $compiled"
}
$final = Join-Path $output "$baseName.exe"
Move-Item -LiteralPath $compiled -Destination $final -Force
$installedMetadata = Join-Path $output 'RELEASE_METADATA.json'
Copy-Item -LiteralPath $releaseMetadata -Destination $installedMetadata -Force
$publishedCompilerLog = Join-Path $output 'iscc.log'
Copy-Item -LiteralPath $compilerLog -Destination $publishedCompilerLog -Force

$started.Stop()
$hash = Get-FileHash -LiteralPath $final -Algorithm SHA256
$installerSignature = Get-AuthenticodeSignature -LiteralPath $final
$report = [ordered]@{
    schema_version = 1
    application_version = $version
    git_commit = $head
    working_tree_change_count = @($status).Count
    cpu_dist = $cpu
    output = $final
    output_bytes = (Get-Item -LiteralPath $final).Length
    output_sha256 = $hash.Hash
    build_seconds = [Math]::Round($started.Elapsed.TotalSeconds, 3)
    inno_setup_version = $innoVersion
    iscc_path = $iscc
    iscc_signature = [string]$signature.Status
    iscc_publisher = $signature.SignerCertificate.Subject
    iscc_log = $publishedCompilerLog
    inno_warning_count = $compilerWarnings.Count
    inno_warnings = @($compilerWarnings | ForEach-Object { [string]$_ })
    installer_authenticode = [string]$installerSignature.Status
    unsigned_expected = $true
}
$reportPath = Join-Path $output 'build-report.json'
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding utf8
$report | ConvertTo-Json -Depth 8
