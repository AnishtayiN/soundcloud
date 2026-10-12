; Self-contained per-user install. Never downloads/installs Python or pip.
#ifndef AppVersion
  #define AppVersion "1.0.1"
#endif
[Setup]
AppId={{B75C9D06-4D4D-4CF1-9F56-EC5ADDB9DC47}
AppName=SoundCloud X
AppVersion={#AppVersion}
AppPublisher=SoundCloud X contributors
AppPublisherURL=https://github.com/AnishtayiN/soundcloud
DefaultDirName={localappdata}\Programs\SoundCloudX
DefaultGroupName=SoundCloud X
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=6.1sp1
OutputDir=dist
OutputBaseFilename=SoundCloudX-Setup-{#AppVersion}-x64
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\SoundCloudX.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
LicenseFile=..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\SoundCloudX.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SoundCloud X"; Filename: "{app}\SoundCloudX.exe"
Name: "{group}\Run offline diagnostics"; Filename: "{app}\SoundCloudX.exe"; Parameters: "--self-test"
Name: "{group}\Uninstall SoundCloud X"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SoundCloud X"; Filename: "{app}\SoundCloudX.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SoundCloudX.exe"; Description: "Launch SoundCloud X"; Flags: nowait postinstall skipifsilent
