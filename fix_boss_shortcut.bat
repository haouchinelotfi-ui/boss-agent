@echo off
chcp 65001 >nul
title Creation du raccourci Boss Agent
color 0B

echo.
echo  Creation du raccourci Boss Agent sur le Bureau...
echo.

REM Trouver le vrai Bureau (normal OU OneDrive)
set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%\OneDrive\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%\OneDrive\Bureau"

if not exist "%DESKTOP%" (
  echo  [ERREUR] Impossible de trouver ton Bureau.
  pause
  exit /b 1
)

echo  Bureau detecte : %DESKTOP%
echo.

REM Dossier stable du Boss
set "DIR=%USERPROFILE%\boss_agent"
if not exist "%DIR%" mkdir "%DIR%"

REM Chemin pythonw
for /f "delims=" %%i in ('where pythonw 2^>nul') do set "PYTHONW=%%i"
if "%PYTHONW%"=="" (
  for /f "delims=" %%i in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYTHONW=%%i"
)

echo  Pythonw : %PYTHONW%
echo.

REM Script de lancement
set "LAUNCH=%DIR%\boss_launch.pyw"
set "ICON=%DIR%\boss.ico"
set "LNK=%DESKTOP%\Boss Agent.lnk"

powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$sc = $ws.CreateShortcut('%LNK%');" ^
  "$sc.TargetPath = '%PYTHONW%';" ^
  "$sc.Arguments = '\"%LAUNCH%\"';" ^
  "$sc.WorkingDirectory = '%DIR%';" ^
  "$sc.IconLocation = '%ICON%,0';" ^
  "$sc.Description = 'Boss Agent - Manager autonome';" ^
  "$sc.WindowStyle = 1;" ^
  "$sc.Save();"

if exist "%LNK%" (
  echo  [OK] Raccourci cree : %LNK%
  echo.
  echo  L'icone "Boss Agent" est sur ton Bureau.
) else (
  echo  [ERREUR] Le raccourci n'a pas ete cree.
)

echo.
pause
exit
