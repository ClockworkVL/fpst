[Setup]
AppId={{6F06CBDF-8C7B-4EF7-93F6-9E9D5EA2D516}
AppName=Farpost Finder
AppVersion=1.0.0
AppPublisher=Farpost Finder
DefaultDirName={localappdata}\Programs\Farpost Finder
DefaultGroupName=Farpost Finder
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
OutputDir=..
OutputBaseFilename=FarpostFinder_Installer
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\FarpostFinder.exe
CloseApplications=yes
CloseApplicationsFilter=FarpostFinder.exe

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\\dist\\FarpostFinder\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\\Farpost Finder"; Filename: "{app}\\FarpostFinder.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\\Farpost Finder"; Filename: "{app}\\FarpostFinder.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\\FarpostFinder.exe"; Description: "{cm:LaunchProgram,Farpost Finder}"; Flags: nowait postinstall skipifsilent
