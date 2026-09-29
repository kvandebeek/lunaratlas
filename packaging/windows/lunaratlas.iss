; Inno Setup script for LunarAtlas: packaging/build.py runs it with /DVersion=… /DSource=dist\LunarAtlas.
; Per-user install (no administrator rights): %LOCALAPPDATA%\Programs\LunarAtlas, a Start-menu entry and an
; optional desktop shortcut. The reference data (≈ 130 MB, downloaded on first use) is kept in
; %LOCALAPPDATA%\LunarAtlas and survives updates; the uninstaller leaves it and the user's photos alone.
#ifndef Version
  #define Version "0.1.0"
#endif
#ifndef Source
  #define Source "..\..\dist\LunarAtlas"
#endif

[Setup]
AppId={{6C1B9E57-4E0A-4F3B-9E0D-9A1C2B7D3F41}
AppName=LunarAtlas
AppVersion={#Version}
AppPublisher=Kristof Vandebeek
AppPublisherURL=https://github.com/kvandebeek/lunaratlas
DefaultDirName={localappdata}\Programs\LunarAtlas
DefaultGroupName=LunarAtlas
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\icon\windows\LunarAtlas.ico
UninstallDisplayIcon={app}\LunarAtlas.exe
LicenseFile=..\..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#Source}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LunarAtlas"; Filename: "{app}\LunarAtlas.exe"
Name: "{autodesktop}\LunarAtlas"; Filename: "{app}\LunarAtlas.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LunarAtlas.exe"; Description: "{cm:LaunchProgram,LunarAtlas}"; Flags: nowait postinstall skipifsilent
