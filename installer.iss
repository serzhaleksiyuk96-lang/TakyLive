; Установщик TakyLive — собирается на GitHub (Inno Setup 6)
#ifndef AppVersion
  #define AppVersion "0.0"
#endif

[Setup]
AppId={{6F1C2A7E-4B9D-4E8A-9C3F-7A1B2D3E4F50}
AppName=TakyLive
AppVersion={#AppVersion}
AppVerName=TakyLive {#AppVersion}
AppPublisher=TakymiVG
DefaultDirName={localappdata}\Programs\TakyLive
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=TakyLive-Setup-{#AppVersion}
SetupIconFile=web\takylive.ico
UninstallDisplayIcon={app}\TakyLive.exe
UninstallDisplayName=TakyLive
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Ярлыки:"

[Files]
Source: "dist\TakyLive\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\TakyLive"; Filename: "{app}\TakyLive.exe"; IconFilename: "{app}\web\takylive.ico"
Name: "{autodesktop}\TakyLive"; Filename: "{app}\TakyLive.exe"; IconFilename: "{app}\web\takylive.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\TakyLive.exe"; Description: "Запустить TakyLive"; Flags: nowait postinstall skipifsilent

; Настройки, вкладки, голоса зрителей, серверы и миры при удалении НЕ стираются —
; удаляются только файлы самой программы. Переустановишь — всё на месте.
