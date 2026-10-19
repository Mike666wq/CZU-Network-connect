; Inno Setup script for Campus Network Assistant - Windows x64.
; Produces a single Setup.exe that installs the PyInstaller onedir layout into
; Program Files, with shortcuts, optional autostart, and a clean uninstaller.
; Compiled by build.ps1 with: iscc installer.iss

#define AppName "校园网助手"
#define AppVersion ReadIni("build\\version.ini", "version", "value", "0.0.0")
#if AppVersion == "0.0.0"
  #define AppVersion "0.0.0-dev"
#endif
#define AppPublisher "Campus Network Assistant"
#define AppId "{{7C2E9B41-3F6A-4E2D-9C5B-8A1F0D2E6B73}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=dist\installer
OutputBaseFilename=campus-network-assistant-Setup-v{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#AppName}.exe
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no


[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked
Name: "autostart"; Description: "登录 Windows 后自动启动校园网助手"; GroupDescription: "附加任务："

[Files]
Source: "dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "CampusNetworkAssistant"; ValueData: """{app}\{#AppName}.exe"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "安装完成后启动校园网助手"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill.exe"; Parameters: "/F /IM {#AppName}.exe"; Flags: runhidden; RunOnceId: "killapp"
