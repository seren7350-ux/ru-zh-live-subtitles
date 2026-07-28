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
#ifndef RepoRoot
  #error RepoRoot must be provided by build_installer.ps1
#endif
#ifndef ReleaseMetadata
  #error ReleaseMetadata must be provided by build_installer.ps1
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
OutputBaseFilename=ru-zh-live-subtitles-cpu-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
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
Source: "{#RepoRoot}\README.md"; DestDir: "{app}"; DestName: "README.md"; Flags: ignoreversion
Source: "{#RepoRoot}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; DestName: "THIRD_PARTY_NOTICES.md"; Flags: ignoreversion
Source: "{#SourcePath}\MODEL_SETUP.txt"; DestDir: "{app}"; DestName: "MODEL_SETUP.txt"; Flags: ignoreversion
Source: "{#ReleaseMetadata}"; DestDir: "{app}"; DestName: "RELEASE_METADATA.json"; Flags: ignoreversion

[Icons]
Name: "{group}\Russian–Chinese Live Subtitles"; Filename: "{app}\ru-zh-subtitles.exe"; Parameters: "live-overlay --translation-device cpu --offline --no-auto-start"; WorkingDir: "{app}"
Name: "{group}\Model setup instructions"; Filename: "{app}\MODEL_SETUP.txt"; WorkingDir: "{app}"
Name: "{autodesktop}\Russian–Chinese Live Subtitles"; Filename: "{app}\ru-zh-subtitles.exe"; Parameters: "live-overlay --translation-device cpu --offline --no-auto-start"; WorkingDir: "{app}"; Tasks: desktopicon
