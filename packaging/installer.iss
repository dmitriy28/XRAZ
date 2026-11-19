; Inno Setup 6: установщик ХРАЗа. Собирается build_installer.bat после PyInstaller.
; Ставится для текущего пользователя без прав администратора (%LOCALAPPDATA%\Programs\KHRAZ).
; Данные (настройки, чаты, память, модели речи) — в %APPDATA%\KHRAZ и при удалении программы сохраняются.

#define AppName "KHRAZ"
#define AppVersion "2.0.0"

[Setup]
AppId={{7E3C1A52-6B0E-4C2B-9A11-4B9A3F2D8C71}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Dmitriy
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=KHRAZ-Setup-{#AppVersion}
SetupIconFile=..\assets\img\khraz.ico
UninstallDisplayIcon={app}\KHRAZ.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Дополнительно:"
Name: "autostart"; Description: "Запускать вместе с Windows"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
Source: "..\dist\KHRAZ\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\KHRAZ"; Filename: "{app}\KHRAZ.exe"
Name: "{group}\Папка данных KHRAZ"; Filename: "{userappdata}\KHRAZ"
Name: "{group}\Удалить KHRAZ"; Filename: "{uninstallexe}"
Name: "{autodesktop}\KHRAZ"; Filename: "{app}\KHRAZ.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "KHRAZ"; \
  ValueData: """{app}\KHRAZ.exe"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\KHRAZ.exe"; Description: "Запустить KHRAZ"; Flags: nowait postinstall skipifsilent
Filename: "https://ollama.com/download"; Description: "Открыть страницу загрузки Ollama (если ещё не установлена)"; \
  Flags: shellexec postinstall skipifsilent unchecked
