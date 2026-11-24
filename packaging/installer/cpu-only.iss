; Stable per-user CPU-only installer candidate. Keep AppId unchanged.

#ifndef AppVersion
  #error AppVersion must be provided by build_installer.ps1
#endif
#ifndef VersionInfoVersion
  #error VersionInfoVersion must be provided by build_installer.ps1
#endif
#ifdef SplitPayloads
#ifndef RuntimePartCount
#define RuntimePartCount 0
#endif
#else
#ifndef CpuDist
  #error CpuDist must be provided by build_installer.ps1
#endif
#ifndef ReleaseMetadata
  #error ReleaseMetadata must be provided by build_installer.ps1
#endif
#ifndef ModelAssetsRoot
  #error ModelAssetsRoot must be provided by build_installer.ps1
#endif
#ifndef ModelBundleMetadata
  #error ModelBundleMetadata must be provided by build_installer.ps1
#endif

#endif

[Setup]
AppId={{8773A11B-6B74-42AF-85AF-CAD43EB946CF}
AppName=Russian–Chinese Live Subtitles
AppVersion={#AppVersion}
VersionInfoVersion={#VersionInfoVersion}
AppPublisher=seren7350-ux
AppPublisherURL=https://github.com/seren7350-ux/ru-zh-live-subtitles
AppSupportURL=https://github.com/seren7350-ux/ru-zh-live-subtitles
DefaultDirName={localappdata}\Programs\RuZhLiveSubtitles
DefaultGroupName=Russian–Chinese Live Subtitles
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
#ifdef SplitPayloads
OutputBaseFilename=setup
ArchiveExtraction=full
#else
OutputBaseFilename=ru-zh-live-subtitles-cpu-offline-{#AppVersion}-setup
#endif
Compression=lzma2
SolidCompression=yes
LZMANumBlockThreads=4
#ifdef DiskSpanning
DiskSpanning=yes
DiskSliceSize=1900000000
SlicesPerDisk=1
#endif
WizardStyle=modern
UninstallDisplayIcon={app}\ru-zh-subtitles.exe
CloseApplications=yes
RestartApplications=no
AllowNoIcons=yes
SetupLogging=yes
ChangesEnvironment=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

#ifdef SplitPayloads
[InstallDelete]
; The onedir's runtime libraries must be replaced as a unit when they differ.
Type: filesandordirs; Name: "{app}\_internal"; Check: InstallRuntime
Type: filesandordirs; Name: "{app}\_internal\ru_zh_live_subtitles-*.dist-info"
Type: files; Name: "{app}\RELEASE_METADATA.json"

[Files]
Source: "{#RuntimeFileManifest}"; DestName: "runtime-files.txt"; Flags: dontcopy
Source: "{tmp}\runtime\_internal\*"; DestDir: "{app}\_internal"; Flags: external ignoreversion recursesubdirs createallsubdirs; Check: InstallRuntime
Source: "{tmp}\runtime\models\*"; DestDir: "{localappdata}\ru-zh-live-subtitles\models"; Flags: external ignoreversion recursesubdirs createallsubdirs; Check: InstallRuntime
Source: "{tmp}\app\*"; DestDir: "{app}"; Flags: external ignoreversion recursesubdirs createallsubdirs
#else
[Files]
Source: "{#CpuDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ReleaseMetadata}"; DestDir: "{app}"; DestName: "RELEASE_METADATA.json"; Flags: ignoreversion
Source: "{#ModelBundleMetadata}"; DestDir: "{app}"; DestName: "MODEL_BUNDLE_METADATA.json"; Flags: ignoreversion
Source: "{#ModelAssetsRoot}\*"; DestDir: "{localappdata}\ru-zh-live-subtitles\models"; Flags: ignoreversion recursesubdirs createallsubdirs

#endif

[Icons]
Name: "{group}\Russian–Chinese Live Subtitles"; Filename: "{app}\ru-zh-subtitles.exe"; Parameters: "live-overlay --translation-device cpu --offline"; WorkingDir: "{app}"
Name: "{group}\Model setup instructions"; Filename: "{app}\MODEL_SETUP.txt"; WorkingDir: "{app}"
Name: "{autodesktop}\Russian–Chinese Live Subtitles"; Filename: "{app}\ru-zh-subtitles.exe"; Parameters: "live-overlay --translation-device cpu --offline"; WorkingDir: "{app}"; Tasks: desktopicon

#ifdef SplitPayloads
[Code]
var
  NeedRuntime: Boolean;
  ExtractionPage: TExtractionWizardPage;

function InstallRuntime: Boolean;
begin
  Result := NeedRuntime;
end;

procedure InitializeWizard;
begin
  ExtractionPage := CreateExtractionPage('Extracting offline packages',
    'Please wait while Setup unpacks the installation files.', nil);
  ExtractionPage.ShowArchiveInsteadOfFile := True;
end;

procedure RegisterExtraCloseApplicationsResources;
begin
  RegisterExtraCloseApplicationsResource(ExpandConstant('{app}\ru-zh-subtitles.exe'));
  RegisterExtraCloseApplicationsResource(ExpandConstant('{app}\ru-zh-subtitles-console.exe'));
end;

function InstalledRuntimeMatches: Boolean;
var
  Entries: TArrayOfString;
  I: Integer;
  RelativeName, Target: String;
begin
  Result := False;
  ExtractTemporaryFile('runtime-files.txt');
  if not LoadStringsFromFile(ExpandConstant('{tmp}\runtime-files.txt'), Entries) then
    RaiseException('Setup could not read its runtime manifest.');
  for I := 0 to GetArrayLength(Entries) - 1 do
  begin
    RelativeName := Copy(Entries[I], 66, MaxInt);
    StringChangeEx(RelativeName, '/', '\', True);
    if Copy(RelativeName, 1, 7) = 'models\' then
      Target := ExpandConstant('{localappdata}\ru-zh-live-subtitles\') + RelativeName
    else
      Target := ExpandConstant('{app}\') + RelativeName;
    if not FileExists(Target) then
      Exit;
    if CompareText(GetSHA256OfFile(Target), Copy(Entries[I], 1, 64)) <> 0 then
      Exit;
  end;
  Result := GetArrayLength(Entries) > 0;
end;

procedure RequireArchive(const FileName: String);
begin
  if not FileExists(FileName) then
    RaiseException('Keep ' + ExtractFileName(FileName) + ' beside setup.exe, then run Setup again.');
end;

procedure CheckArchive(const FileName, ExpectedHash: String);
begin
  RequireArchive(FileName);
  if CompareText(GetSHA256OfFile(FileName), ExpectedHash) <> 0 then
    RaiseException(ExtractFileName(FileName) + ' is damaged or belongs to a different setup.');
end;

#if Int(RuntimePartCount) > 0
function RuntimePartPath(Index: Integer): String;
begin
  Result := ExpandConstant('{src}\') + Format('runtime.zip.%.3d', [Index]);
end;

procedure JoinRuntimeParts(const Destination: String);
var
  Index: Integer;
  Source, Target: TFileStream;
begin
  for Index := 1 to {#RuntimePartCount} do
    RequireArchive(RuntimePartPath(Index));

  Log('Offline packages: joining {#RuntimePartCount} runtime.zip parts.');
  Target := TFileStream.Create(Destination, fmCreate);
  try
    for Index := 1 to {#RuntimePartCount} do
    begin
      Source := TFileStream.Create(RuntimePartPath(Index), fmOpenRead or fmShareDenyWrite);
      try
        Target.CopyFrom(Source, 0, $100000);
      finally
        Source.Free;
      end;
    end;
  finally
    Target.Free;
  end;
end;
#endif

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  AppZip, RuntimeZip, AppStage, RuntimeStage: String;
begin
  Result := '';
  try
    AppZip := ExpandConstant('{src}\app.zip');
    AppStage := ExpandConstant('{tmp}\app');
    RuntimeStage := ExpandConstant('{tmp}\runtime');
    CheckArchive(AppZip, '{#AppZipSha256}');
    NeedRuntime := not InstalledRuntimeMatches;
    ExtractionPage.Clear;
    if NeedRuntime then
    begin
#if Int(RuntimePartCount) > 0
      RuntimeZip := ExpandConstant('{tmp}\runtime.zip');
      JoinRuntimeParts(RuntimeZip);
#else
      RuntimeZip := ExpandConstant('{src}\runtime.zip');
#endif
      CheckArchive(RuntimeZip, '{#RuntimeZipSha256}');
      ForceDirectories(RuntimeStage);
      ExtractionPage.Add(RuntimeZip, RuntimeStage, True);
      Log('Offline packages: installing runtime.zip.');
    end
    else
      Log('Offline packages: reusing matching installed runtime files.');
    ForceDirectories(AppStage);
    ExtractionPage.Add(AppZip, AppStage, True);
    ExtractionPage.Show;
    try
      ExtractionPage.Extract;
    finally
      ExtractionPage.Hide;
    end;
  except
    Result := GetExceptionMessage;
  end;
end;
#else
[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\ru-zh-live-subtitles"

[Code]
const
  MinimumFreeBytes = 12884901888;

function InitializeSetup: Boolean;
var
  FreeBytes, TotalBytes: Int64;
  TargetDrive: String;
begin
  Result := False;
  TargetDrive := ExpandConstant('{localappdata}');
  if not GetSpaceOnDisk64(TargetDrive, FreeBytes, TotalBytes) then
  begin
    MsgBox('Setup could not determine free disk space for ' + TargetDrive + '.',
      mbError, MB_OK);
    Exit;
  end;
  if FreeBytes < MinimumFreeBytes then
  begin
    MsgBox(
      'At least 12 GiB of free disk space is required before installation.' + #13#10 +
      'Available: ' + IntToStr(FreeBytes) + ' bytes.', mbError, MB_OK);
    Exit;
  end;
  Result := True;
end;
#endif
