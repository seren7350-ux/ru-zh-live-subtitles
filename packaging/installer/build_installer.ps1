[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$RepoRoot,
    [Parameter(Mandatory = $false)]
    [string]$CpuDist,
    [Parameter(Mandatory = $false)]
    [string]$ModelAssetsRoot,
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
    [string]$TestModelBundleMetadataPath,
    [Parameter(Mandatory = $false)]
    [ValidateSet('None', 'CpuPolicy', 'ModelBundle', 'Iscc', 'Report')]
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
    if (-not $TestModelBundleMetadataPath -or
        -not (Test-Path -LiteralPath $TestModelBundleMetadataPath -PathType Leaf)) {
        throw 'TestMode requires a test model bundle metadata fixture.'
    }
}

$started = [Diagnostics.Stopwatch]::StartNew()
$repo = Resolve-ExistingDirectory $RepoRoot 'Repository root'
$version = Read-ApplicationVersion $repo
if (-not $CpuDist) { $CpuDist = Join-Path $repo 'dist\ru-zh-subtitles-cpu' }
if (-not $OutputDir) { $OutputDir = Join-Path $repo 'dist\installer-offline' }
$output = [IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $output | Out-Null

$baseName = "ru-zh-live-subtitles-cpu-offline-$version-setup"
$finalSetup = Join-Path $output "$baseName.exe"
$finalMetadata = Join-Path $output 'RELEASE_METADATA.json'
$finalBundleMetadata = Join-Path $output 'MODEL_BUNDLE_METADATA.json'
$finalReport = Join-Path $output 'build-report.json'
$finalCompilerLog = Join-Path $output 'iscc.log'
$finalReadme = Join-Path $output 'README_INSTALL.txt'
$finalSlices = @(Get-ChildItem -LiteralPath $output -Filter "$baseName-*.bin" -File -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
$finalPaths = @($finalMetadata, $finalBundleMetadata, $finalCompilerLog, $finalReport, $finalReadme, $finalSetup) + $finalSlices
Remove-ExactCandidateFiles $finalPaths
if (-not $ModelAssetsRoot) {
    throw 'ModelAssetsRoot is required. The offline installer never falls back to a user Hugging Face cache.'
}

$temporary = Join-Path $output ('.build-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
$temporaryPrefix = $output.TrimEnd('\') + '\.build-'
if (-not $temporary.StartsWith($temporaryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Unsafe temporary installer path.'
}

try {
    if ($TestMode) {
        Assert-IsolatedTestMode $repo $output
    } elseif ($TestFailureStage -ne 'None' -or $TestDoctorOutputPath -or $TestModelBundleMetadataPath) {
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
    $models = Resolve-ExistingDirectory $ModelAssetsRoot 'Model assets root'
    $python = if ($PythonPath) { [IO.Path]::GetFullPath($PythonPath) } else {
        Join-Path $repo '.venv-packaging-cpu\Scripts\python.exe'
    }
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'CPU packaging Python is missing.'
    }
    $validator = Join-Path $repo 'packaging\validate_cpu_distribution.py'
    $metadataTool = Join-Path $repo 'packaging\installer\release_metadata.py'
    $modelBundleTool = Join-Path $repo 'packaging\model_bundle.py'
    $iss = Join-Path $repo 'packaging\installer\cpu-only.iss'
    $readmeInstall = Join-Path $repo 'packaging\installer\README_INSTALL.txt'
    $modelLicenses = Join-Path $repo 'packaging\installer\MODEL_LICENSES.txt'
    foreach ($requiredTool in @($validator, $metadataTool, $modelBundleTool, $iss, $readmeInstall, $modelLicenses)) {
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

    $bundleMetadata = Join-Path $temporary 'MODEL_BUNDLE_METADATA.json'
    $modelVerification = [Diagnostics.Stopwatch]::StartNew()
    if ($TestMode) {
        Copy-Item -LiteralPath $TestModelBundleMetadataPath -Destination $bundleMetadata
    } else {
        & $python $modelBundleTool $models --output $bundleMetadata | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Full model bundle validation failed.' }
    }
    $modelVerification.Stop()
    if ($TestFailureStage -eq 'ModelBundle') { throw 'Injected model bundle failure.' }
    $bundle = Get-Content -LiteralPath $bundleMetadata -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($bundle.schema_version -ne 1 -or
        $bundle.bundle_type -ne 'offline-model-assets' -or
        $bundle.file_count -le 0 -or
        $bundle.total_bytes -le 0 -or
        $bundle.gigaam_revision -ne '322c3b29492673eb7d0b434bfa9dfb8653e34d02' -or
        $bundle.nllb_revision -ne 'f8d333a098d19b4fd9a8b18f94170487ad3f821d') {
        throw 'Model bundle metadata does not describe the pinned offline bundle.'
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
    & $python $metadataTool --repo-root $repo --cpu-dist $cpu --expected-commit $ExpectedCommit --inno-version $innoVersion --model-bundle-metadata $bundleMetadata --output $releaseMetadata --full-manifest | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Release metadata generation failed.' }
    $release = Get-Content -LiteralPath $releaseMetadata -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($release.git_commit -ne $ExpectedCommit -or
        $release.cpu_build_provenance.git_commit -ne $ExpectedCommit -or
        $release.cpu_build_provenance.application_version -ne $version -or
        -not $release.self_contained -or
        -not $release.offline_ready -or
        $release.model_bundle.manifest_sha256 -ne $bundle.manifest_sha256) {
        throw 'Release metadata is not bound to the validated CPU distribution.'
    }

    $commonArguments = @(
        '/Qp',
        "/O$temporary",
        "/F$baseName",
        "/DAppVersion=$version",
        "/DVersionInfoVersion=$version.0",
        "/DCpuDist=$cpu",
        "/DReleaseMetadata=$releaseMetadata",
        "/DModelAssetsRoot=$models",
        "/DModelBundleMetadata=$bundleMetadata"
    )
    $innoCompilation = [Diagnostics.Stopwatch]::StartNew()
    $arguments = @($commonArguments) + @($iss)
    $compilerOutput = @(& $iscc @arguments 2>&1)
    $compilerExitCode = $LASTEXITCODE
    if ($TestFailureStage -eq 'Iscc' -and $compilerExitCode -eq 0) {
        $compilerExitCode = 97
    }
    $diskSpanning = $false
    if ($compilerExitCode -ne 0) {
        $compilerFailureText = $compilerOutput -join "`n"
        if ($compilerFailureText -match '(?i)disk spanning|compressed[^\r\n]*too large|4[,.]?200[,.]?000[,.]?000') {
            $diskSpanning = $true
        } else {
            throw "Inno Setup compilation failed with exit code $compilerExitCode."
        }
    }
    $compiled = Join-Path $temporary "$baseName.exe"
    if (-not $diskSpanning -and -not (Test-Path -LiteralPath $compiled -PathType Leaf)) {
        throw 'Inno Setup did not produce the expected installer.'
    }
    if (-not $diskSpanning -and (Get-Item -LiteralPath $compiled).Length -ge 3800000000) {
        $diskSpanning = $true
    }
    if ($diskSpanning) {
        Get-ChildItem -LiteralPath $temporary -Filter "$baseName*" -File |
            Remove-Item -Force
        $spanningArguments = @($commonArguments) + @('/DDiskSpanning=1', $iss)
        $spanningOutput = @(& $iscc @spanningArguments 2>&1)
        $compilerExitCode = $LASTEXITCODE
        $compilerOutput = @($compilerOutput) + @('--- disk-spanning rebuild ---') + @($spanningOutput)
        if ($compilerExitCode -ne 0) {
            throw "Inno Setup disk-spanning compilation failed with exit code $compilerExitCode."
        }
        if (-not (Test-Path -LiteralPath $compiled -PathType Leaf)) {
            throw 'Inno Setup disk-spanning compilation did not produce setup.exe.'
        }
    }
    $innoCompilation.Stop()
    $compilerLog = Join-Path $temporary 'iscc.log'
    Set-Content -LiteralPath $compilerLog -Value $compilerOutput -Encoding utf8
    $compilerWarnings = @($compilerOutput | Where-Object { [string]$_ -match '(?i)\bwarning\b' })

    $compiledSlices = @(
        Get-ChildItem -LiteralPath $temporary -Filter "$baseName-*.bin" -File |
            Sort-Object Name
    )
    if ($diskSpanning -and $compiledSlices.Count -eq 0) {
        throw 'Disk spanning was selected but Inno Setup produced no numbered data slices.'
    }
    $payloadItems = @($compiledSlices) + @(Get-Item -LiteralPath $compiled)
    $payloadRecords = @(
        $payloadItems | ForEach-Object {
            [pscustomobject][ordered]@{
                name = $_.Name
                size_bytes = $_.Length
                sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
            }
        }
    )
    $payloadBytes = [int64](($payloadRecords | Measure-Object -Property size_bytes -Sum).Sum)
    $cpuBytes = [int64]$release.cpu_distribution.total_bytes
    $modelBytes = [int64]$bundle.total_bytes
    $uncompressedBytes = $cpuBytes + $modelBytes
    $installerSignature = if ($TestMode) { 'NotSigned' } else {
        [string](Get-AuthenticodeSignature -LiteralPath $compiled).Status
    }
    $readmeCopy = Join-Path $temporary 'README_INSTALL.txt'
    Copy-Item -LiteralPath $readmeInstall -Destination $readmeCopy
    $started.Stop()
    $report = [ordered]@{
        schema_version = 3
        application_version = $version
        git_commit = $head
        working_tree_change_count = 0
        cpu_build_provenance = $policy.cpu_build_provenance
        cpu_dist = $cpu
        cpu_dist_bytes = $cpuBytes
        model_bundle_bytes = $modelBytes
        model_file_count = [int]$bundle.file_count
        model_manifest_sha256 = [string]$bundle.manifest_sha256
        total_uncompressed_bytes = $uncompressedBytes
        model_verification_seconds = [Math]::Round($modelVerification.Elapsed.TotalSeconds, 3)
        inno_compilation_seconds = [Math]::Round($innoCompilation.Elapsed.TotalSeconds, 3)
        output = $finalSetup
        output_mode = if ($diskSpanning) { 'disk-spanning' } else { 'single-file' }
        output_files = $payloadRecords
        output_bytes = $payloadBytes
        compression_ratio = if ($uncompressedBytes -gt 0) {
            [Math]::Round($payloadBytes / $uncompressedBytes, 6)
        } else { $null }
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
        publication_order = @(
            'RELEASE_METADATA.json',
            'MODEL_BUNDLE_METADATA.json',
            'iscc.log',
            'build-report.json',
            'README_INSTALL.txt'
        ) + @($compiledSlices | ForEach-Object { $_.Name }) + @("$baseName.exe")
        setup_published_last = $true
    }
    if ($TestFailureStage -eq 'Report') { throw 'Injected build report failure.' }
    $reportPath = Join-Path $temporary 'build-report.json'
    $report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $reportPath -Encoding utf8
    $null = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json

    $publicationTime = [DateTime]::UtcNow
    Move-Item -LiteralPath $releaseMetadata -Destination $finalMetadata
    [IO.File]::SetLastWriteTimeUtc($finalMetadata, $publicationTime)
    Move-Item -LiteralPath $bundleMetadata -Destination $finalBundleMetadata
    [IO.File]::SetLastWriteTimeUtc($finalBundleMetadata, $publicationTime.AddMilliseconds(10))
    Move-Item -LiteralPath $compilerLog -Destination $finalCompilerLog
    [IO.File]::SetLastWriteTimeUtc($finalCompilerLog, $publicationTime.AddMilliseconds(20))
    Move-Item -LiteralPath $reportPath -Destination $finalReport
    [IO.File]::SetLastWriteTimeUtc($finalReport, $publicationTime.AddMilliseconds(30))
    Move-Item -LiteralPath $readmeCopy -Destination $finalReadme
    [IO.File]::SetLastWriteTimeUtc($finalReadme, $publicationTime.AddMilliseconds(40))
    $timestampOffset = 50
    foreach ($slice in $compiledSlices) {
        $destination = Join-Path $output $slice.Name
        Move-Item -LiteralPath $slice.FullName -Destination $destination
        [IO.File]::SetLastWriteTimeUtc($destination, $publicationTime.AddMilliseconds($timestampOffset))
        $timestampOffset += 10
    }
    Move-Item -LiteralPath $compiled -Destination $finalSetup
    [IO.File]::SetLastWriteTimeUtc($finalSetup, $publicationTime.AddMilliseconds($timestampOffset))

    Get-Content -LiteralPath $finalReport -Raw -Encoding UTF8
} catch {
    $publishedSlices = @(
        Get-ChildItem -LiteralPath $output -Filter "$baseName-*.bin" -File -ErrorAction SilentlyContinue |
            ForEach-Object { $_.FullName }
    )
    Remove-ExactCandidateFiles ($finalPaths + $publishedSlices)
    throw
} finally {
    if ($temporary.StartsWith($temporaryPrefix, [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $temporary -PathType Container)) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
