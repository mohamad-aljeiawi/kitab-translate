; Inno Setup script for the Windows installer. packaging/build.py runs it as
;   iscc /DAppVersion=0.1.0 /DSourceDir=...\dist\kitab /DOutputDir=...\dist kitab.iss
;
; Per-user by default (no administrator prompt), into %LOCALAPPDATA%\Programs\Kitab;
; the dialog offers an all-users install for those who want one.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\kitab"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif

[Setup]
AppId={{6A0E3F0B-2C4D-4E7A-9C51-8B1D2F4A7E93}
AppName=Kitab
AppVersion={#AppVersion}
AppVerName=Kitab {#AppVersion}
AppPublisher=mohamad-aljeiawi
AppPublisherURL=https://github.com/mohamad-aljeiawi/kitab-translate
AppSupportURL=https://github.com/mohamad-aljeiawi/kitab-translate/issues
DefaultDirName={autopf}\Kitab
DefaultGroupName=Kitab
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\..\LICENSE
SetupIconFile=..\..\build\icon.ico
UninstallDisplayIcon={app}\kitab.exe
OutputDir={#OutputDir}
OutputBaseFilename=Kitab-{#AppVersion}-windows-x64-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Kitab"; Filename: "{app}\kitab.exe"
Name: "{autodesktop}\Kitab"; Filename: "{app}\kitab.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\kitab.exe"; Description: "{cm:LaunchProgram,Kitab}"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; A new version replaces the bundled libraries wholesale; stale ones from an older
; build must not be picked up. Settings, keys and work files live elsewhere.
Type: filesandordirs; Name: "{app}\_internal"
