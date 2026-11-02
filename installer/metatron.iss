; METATRON installer (Inno Setup 6). Built by installer/build.py, which passes
; AppVersion, BuildDir (the assembled app folder) and OutDir.
;
; Per-user install, no admin rights: the app goes to %LOCALAPPDATA%\Programs\METATRON and the
; broker's data to %LOCALAPPDATA%\METATRON (kept on uninstall, so a reinstall keeps clients).

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6F1C2A7E-3B54-4C8E-9A21-5D7E0B9F4C11}
AppName=METATRON
AppVersion={#AppVersion}
AppPublisher=METATRON
DefaultDirName={localappdata}\Programs\METATRON
DefaultGroupName=METATRON
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=METATRON-Setup-{#AppVersion}
SetupIconFile={#SourcePath}metatron.ico
UninstallDisplayIcon={app}\metatron.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "he"; MessagesFile: "compiler:Languages\Hebrew.isl"

[CustomMessages]
he.Desktop=קיצור דרך על שולחן העבודה
he.Autostart=הפעלה אוטומטית עם Windows (כדי שתשובות של מוכרים יטופלו גם כשהדשבורד סגור)
he.Launch=פתיחת METATRON
he.DetailsTitle=הפרטים שלך
he.DetailsSub=METATRON ישלח הודעות בשמך מהוואטסאפ שלך
he.DetailsHelp=מספר הוואטסאפ ישמש לחיבור בשלב הבא: תקבל/י קוד בן 8 תווים שמקלידים בוואטסאפ, תחת מכשירים מקושרים.
he.NameLabel=השם שלך (לחתימה בהודעות):
he.PhoneLabel=מספר הוואטסאפ שלך:

[Tasks]
Name: "desktop"; Description: "{cm:Desktop}"
Name: "autostart"; Description: "{cm:Autostart}"

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\METATRON"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m metatron.product.launcher"; WorkingDir: "{app}"; IconFilename: "{app}\metatron.ico"
Name: "{userdesktop}\METATRON"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m metatron.product.launcher"; WorkingDir: "{app}"; IconFilename: "{app}\metatron.ico"; Tasks: desktop
Name: "{userstartup}\METATRON"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m metatron.product.launcher --no-browser"; WorkingDir: "{app}"; IconFilename: "{app}\metatron.ico"; Tasks: autostart

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-m metatron.product.launcher"; WorkingDir: "{app}"; Description: "{cm:Launch}"; Flags: postinstall nowait skipifsilent

[Code]
var
  DetailsPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  DetailsPage := CreateInputQueryPage(wpSelectTasks, CustomMessage('DetailsTitle'),
    CustomMessage('DetailsSub'), CustomMessage('DetailsHelp'));
  DetailsPage.Add(CustomMessage('NameLabel'), False);
  DetailsPage.Add(CustomMessage('PhoneLabel'), False);
end;

function JsonEscape(S: String): String;
begin
  StringChangeEx(S, '\', '\\', True);
  StringChangeEx(S, '"', '\"', True);
  Result := S;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Lines: TArrayOfString;
  Dir: String;
begin
  if CurStep = ssPostInstall then
  begin
    Dir := ExpandConstant('{localappdata}\METATRON');
    ForceDirectories(Dir);
    SetArrayLength(Lines, 1);
    Lines[0] := '{"broker_name": "' + JsonEscape(Trim(DetailsPage.Values[0])) +
                '", "wa_phone": "' + JsonEscape(Trim(DetailsPage.Values[1])) + '"}';
    SaveStringsToUTF8File(Dir + '\install.json', Lines, False);
  end;
end;
