; Stable per-user CPU-only installer candidate. Keep AppId unchanged.

#ifndef AppVersion
  #error AppVersion must be provided by build_installer.ps1
#endif
#ifndef VersionInfoVersion
  #error VersionInfoVersion must be provided by build_installer.ps1
#endif
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
OutputBaseFilename=ru-zh-live-subtitles-cpu-offline-{#AppVersion}-setup
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

[Files]
Source: "{#CpuDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ReleaseMetadata}"; DestDir: "{app}"; DestName: "RELEASE_METADATA.json"; Flags: ignoreversion
Source: "{#ModelBundleMetadata}"; DestDir: "{app}"; DestName: "MODEL_BUNDLE_METADATA.json"; Flags: ignoreversion
Source: "{#ModelAssetsRoot}\*"; DestDir: "{localappdata}\ru-zh-live-subtitles\models"; Flags: ignoreversion recursesubdirs createallsubdirs uninsneveruninstall

[Icons]
Name: "{group}\Russian–Chinese Live Subtitles"; Filename: "{app}\ru-zh-subtitles.exe"; Parameters: "live-overlay --translation-device cpu --offline --no-auto-start"; WorkingDir: "{app}"
Name: "{group}\Model setup instructions"; Filename: "{app}\MODEL_SETUP.txt"; WorkingDir: "{app}"
Name: "{autodesktop}\Russian–Chinese Live Subtitles"; Filename: "{app}\ru-zh-subtitles.exe"; Parameters: "live-overlay --translation-device cpu --offline --no-auto-start"; WorkingDir: "{app}"; Tasks: desktopicon

[Code]
const
  MinimumFreeBytes = 8589934592;

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
      'At least 8 GiB of free disk space is required before installation.' + #13#10 +
      'Available: ' + IntToStr(FreeBytes) + ' bytes.', mbError, MB_OK);
    Exit;
  end;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    MsgBox(
      'Model assets were preserved. Delete the following folder manually to reclaim disk space:' +
      Chr(13) + Chr(10) + ExpandConstant('{localappdata}\ru-zh-live-subtitles\models'),
      mbInformation, MB_OK);
end;
