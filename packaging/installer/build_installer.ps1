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
    [string]$IsccPath,
    [Parameter(Mandatory = $false)]
    [string]$PythonPath,
    [Parameter(Mandatory = $false)]
    [switch]$TestMode,
    [Parameter(Mandatory = $false)]
    [string]$TestDoctorOutputPath,
    [Parameter(Mandatory = $false)]
    [ValidateSet('None', 'CpuPolicy', 'Iscc', 'Report')]
    [string]$TestFailureStage = 'None'
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

function Read-ApplicationVersion([string]$Repository) {
    $source = Join-Path $Repository 'src\live_subtitles\__init__.py'
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw 'The application version source is missing.'
    }
    $match = [regex]::Match(
        (Get-Content -LiteralPath $source -Raw -Encoding UTF8),
        '(?m)^__version__\s*=\s*["'']([^"'']+)["'']\s*$'
    )
    if (-not $match.Success) { throw 'Unable to read the application version.' }
    return $match.Groups[1].Value
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

function Remove-ExactCandidateFiles([string[]]$Paths) {
    foreach ($path in $Paths) {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            Remove-Item -LiteralPath $path -Force
        }
    }
}

function Assert-IsolatedTestMode([string]$Repository, [string]$Destination) {
    $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    $repoFull = [IO.Path]::GetFullPath($Repository).TrimEnd('\') + '\'
    $destinationFull = [IO.Path]::GetFullPath($Destination).TrimEnd('\') + '\'
    if (-not $repoFull.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -or
        -not $destinationFull.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'TestMode is restricted to the system temporary directory.'
    }
    $remotes = @(& git -C $Repository remote)
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect test repository remotes.' }
    if ($remotes -contains 'origin') {
        throw 'TestMode cannot run in a repository with an origin remote.'
    }
    if (-not $TestDoctorOutputPath -or
        -not (Test-Path -LiteralPath $TestDoctorOutputPath -PathType Leaf)) {
        throw 'TestMode requires a test doctor output fixture.'
    }
}

$started = [Diagnostics.Stopwatch]::StartNew()
$repo = Resolve-ExistingDirectory $RepoRoot 'Repository root'
$version = Read-ApplicationVersion $repo
if (-not $CpuDist) { $CpuDist = Join-Path $repo 'dist\ru-zh-subtitles-cpu' }
if (-not $OutputDir) { $OutputDir = Join-Path $repo 'dist\installer' }
$output = [IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $output | Out-Null

$baseName = "ru-zh-live-subtitles-cpu-$version-setup"
$finalSetup = Join-Path $output "$baseName.exe"
$finalMetadata = Join-Path $output 'RELEASE_METADATA.json'
$finalReport = Join-Path $output 'build-report.json'
$finalCompilerLog = Join-Path $output 'iscc.log'
$finalPaths = @($finalMetadata, $finalCompilerLog, $finalReport, $finalSetup)
Remove-ExactCandidateFiles $finalPaths

$temporary = Join-Path $output ('.build-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
$temporaryPrefix = $output.TrimEnd('\') + '\.build-'
if (-not $temporary.StartsWith($temporaryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Unsafe temporary installer path.'
}

try {
    if ($TestMode) {
        Assert-IsolatedTestMode $repo $output
    } elseif ($TestFailureStage -ne 'None' -or $TestDoctorOutputPath) {
        throw 'Test-only parameters require isolated TestMode.'
    }

    $status = @(& git -C $repo status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect the Git working tree.' }
    if ($status.Count -ne 0) {
        $safeChanges = @(
            $status | ForEach-Object {
                $entry = [string]$_
                $code = if ($entry.Length -ge 2) { $entry.Substring(0, 2) } else { '??' }
                $relative = if ($entry.Length -ge 4) { $entry.Substring(3) } else { '<unknown>' }
                if ([IO.Path]::IsPathRooted($relative)) { $relative = '<invalid-path>' }
                "$code $relative"
            }
        )
        throw ('Git working tree is not clean: ' + ($safeChanges -join '; '))
    }
    $head = (& git -C $repo rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
        throw 'Unable to read a valid lowercase Git commit.'
    }
    if ($head -ne $ExpectedCommit) {
        throw "Git commit mismatch: expected $ExpectedCommit, found $head."
    }

    $cpu = Resolve-ExistingDirectory $CpuDist 'CPU distribution'
    $python = if ($PythonPath) { [IO.Path]::GetFullPath($PythonPath) } else {
        Join-Path $repo '.venv-packaging-cpu\Scripts\python.exe'
    }
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'CPU packaging Python is missing.'
    }
    $validator = Join-Path $repo 'packaging\validate_cpu_distribution.py'
    $metadataTool = Join-Path $repo 'packaging\installer\release_metadata.py'
    $iss = Join-Path $repo 'packaging\installer\cpu-only.iss'
    foreach ($requiredTool in @($validator, $metadataTool, $iss)) {
        if (-not (Test-Path -LiteralPath $requiredTool -PathType Leaf)) {
            throw 'A required installer build input is missing.'
        }
    }

    $policyJson = Join-Path $temporary 'cpu-policy.json'
    & $python $validator $cpu --repo-root $repo --expected-commit $ExpectedCommit --json-output $policyJson | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'CPU distribution policy or provenance validation failed.' }
    if ($TestFailureStage -eq 'CpuPolicy') { throw 'Injected CPU policy failure.' }
    $policy = Get-Content -LiteralPath $policyJson -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($policy.runtime_family -ne 'cpu' -or
        $policy.cpu_build_provenance.git_commit -ne $ExpectedCommit) {
        throw 'CPU distribution provenance did not survive policy validation.'
    }

    $oldHubOffline = $env:HF_HUB_OFFLINE
    $oldTransformersOffline = $env:TRANSFORMERS_OFFLINE
    try {
        $env:HF_HUB_OFFLINE = '1'
        $env:TRANSFORMERS_OFFLINE = '1'
        if ($TestMode) {
            $doctorOutput = @(Get-Content -LiteralPath $TestDoctorOutputPath -Encoding UTF8)
        } else {
            $doctorOutput = & (Join-Path $cpu 'ru-zh-subtitles-console.exe') translation-doctor 2>&1
            if ($LASTEXITCODE -ne 0) { throw 'Frozen CPU translation-doctor failed.' }
        }
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

    $iscc = Find-Iscc $IsccPath
    if ($TestMode) {
        $innoVersion = '7.0.2'
        $isccSignatureStatus = 'TestOnly'
        $isccPublisher = 'Test-only isolated compiler fixture'
    } else {
        $signature = Get-AuthenticodeSignature -LiteralPath $iscc
        if ($signature.Status -ne 'Valid' -or
            $signature.SignerCertificate.Subject -notmatch 'Pyrsys B\.V\.') {
            throw 'ISCC.exe does not have the required valid Pyrsys B.V. Authenticode signature.'
        }
        $innoVersion = Get-IsccVersion $iscc
        if ($innoVersion -ne '7.0.2') {
            throw "Inno Setup 7.0.2 is required; found $innoVersion."
        }
        $isccSignatureStatus = [string]$signature.Status
        $isccPublisher = $signature.SignerCertificate.Subject
    }

    $releaseMetadata = Join-Path $temporary 'RELEASE_METADATA.json'
    & $python $metadataTool --repo-root $repo --cpu-dist $cpu --expected-commit $ExpectedCommit --inno-version $innoVersion --output $releaseMetadata --full-manifest | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Release metadata generation failed.' }
    $release = Get-Content -LiteralPath $releaseMetadata -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($release.git_commit -ne $ExpectedCommit -or
        $release.cpu_build_provenance.git_commit -ne $ExpectedCommit -or
        $release.cpu_build_provenance.application_version -ne $version) {
        throw 'Release metadata is not bound to the validated CPU distribution.'
    }

    $arguments = @(
        '/Qp',
        "/O$temporary",
        "/F$baseName",
        "/DAppVersion=$version",
        "/DVersionInfoVersion=$version.0",
        "/DCpuDist=$cpu",
        "/DReleaseMetadata=$releaseMetadata",
        $iss
    )
    $compilerOutput = @(& $iscc @arguments 2>&1)
    $compilerExitCode = $LASTEXITCODE
    $compilerLog = Join-Path $temporary 'iscc.log'
    Set-Content -LiteralPath $compilerLog -Value $compilerOutput -Encoding utf8
    if ($TestFailureStage -eq 'Iscc' -and $compilerExitCode -eq 0) {
        $compilerExitCode = 97
    }
    if ($compilerExitCode -ne 0) {
        throw "Inno Setup compilation failed with exit code $compilerExitCode."
    }
    $compilerWarnings = @($compilerOutput | Where-Object { [string]$_ -match '(?i)\bwarning\b' })

    $compiled = Join-Path $temporary "$baseName.exe"
    if (-not (Test-Path -LiteralPath $compiled -PathType Leaf)) {
        throw 'Inno Setup did not produce the expected installer.'
    }
    $hash = Get-FileHash -LiteralPath $compiled -Algorithm SHA256
    $installerSignature = if ($TestMode) { 'NotSigned' } else {
        [string](Get-AuthenticodeSignature -LiteralPath $compiled).Status
    }
    $started.Stop()
    $report = [ordered]@{
        schema_version = 2
        application_version = $version
        git_commit = $head
        working_tree_change_count = 0
        cpu_build_provenance = $policy.cpu_build_provenance
        cpu_dist = $cpu
        output = $finalSetup
        output_bytes = (Get-Item -LiteralPath $compiled).Length
        output_sha256 = $hash.Hash
        build_seconds = [Math]::Round($started.Elapsed.TotalSeconds, 3)
        inno_setup_version = $innoVersion
        iscc_path = $iscc
        iscc_signature = $isccSignatureStatus
        iscc_publisher = $isccPublisher
        iscc_log = $finalCompilerLog
        inno_warning_count = $compilerWarnings.Count
        inno_warnings = @($compilerWarnings | ForEach-Object { [string]$_ })
        installer_authenticode = $installerSignature
        unsigned_expected = $true
        publication_order = @('RELEASE_METADATA.json', 'iscc.log', 'build-report.json', "$baseName.exe")
        setup_published_last = $true
    }
    if ($TestFailureStage -eq 'Report') { throw 'Injected build report failure.' }
    $reportPath = Join-Path $temporary 'build-report.json'
    $report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $reportPath -Encoding utf8
    $null = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json

    $publicationTime = [DateTime]::UtcNow
    Move-Item -LiteralPath $releaseMetadata -Destination $finalMetadata
    [IO.File]::SetLastWriteTimeUtc($finalMetadata, $publicationTime)
    Move-Item -LiteralPath $compilerLog -Destination $finalCompilerLog
    [IO.File]::SetLastWriteTimeUtc($finalCompilerLog, $publicationTime.AddMilliseconds(10))
    Move-Item -LiteralPath $reportPath -Destination $finalReport
    [IO.File]::SetLastWriteTimeUtc($finalReport, $publicationTime.AddMilliseconds(20))
    Move-Item -LiteralPath $compiled -Destination $finalSetup
    [IO.File]::SetLastWriteTimeUtc($finalSetup, $publicationTime.AddMilliseconds(30))

    Get-Content -LiteralPath $finalReport -Raw -Encoding UTF8
} catch {
    Remove-ExactCandidateFiles $finalPaths
    throw
} finally {
    if ($temporary.StartsWith($temporaryPrefix, [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $temporary -PathType Container)) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
