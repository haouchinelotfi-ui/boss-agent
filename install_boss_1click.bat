@echo off
chcp 65001 >nul
title Installation de Boss Agent
color 0B

echo.
echo  ============================================================
echo             INSTALLATION DE BOSS AGENT  (1-CLIC)
echo  ============================================================
echo.

REM Dossier d'installation
set "DIR=%USERPROFILE%\boss_agent"
if not exist "%DIR%" mkdir "%DIR%"
cd /d "%DIR%"

echo  [1/5] Telechargement des fichiers...
powershell -NoProfile -Command ^
  "$t=[DateTime]::Now.Ticks;" ^
  "$u='https://raw.githubusercontent.com/haouchinelotfi-ui/boss-agent/main';" ^
  "Invoke-WebRequest \"$u/install_boss_shortcut.py?t=$t\" -OutFile install_boss_shortcut.py" ^
  ; Invoke-WebRequest "$u/boss_app.py?t=$t" -OutFile boss_app.py" ^
  ; Invoke-WebRequest "$u/boss_agent.py?t=$t" -OutFile boss_agent.py" ^
  ; Invoke-WebRequest "$u/boss_launch.pyw?t=$t" -OutFile boss_launch.pyw"

if errorlevel 1 (
  echo.
  echo  [ERREUR] Echec du telechargement. Verifie ta connexion internet.
  pause
  exit /b 1
)

echo  [OK] Fichiers telecharges.
echo.

echo  [2/5] Verification de Pillow (pour l'icone)...
python -c "import PIL" 2>nul
if errorlevel 1 (
  echo       Installation de Pillow...
  pip install pillow -q
)
echo  [OK] Pillow pret.
echo.

echo  [3/5] Verification de Streamlit...
python -c "import streamlit" 2>nul
if errorlevel 1 (
  echo       Installation de Streamlit + dependances...
  pip install streamlit pillow python-pptx -q
)
echo  [OK] Streamlit pret.
echo.

echo  [4/5] Creation de l'icone + raccourci Bureau...
python install_boss_shortcut.py
echo.

echo  [5/5] Ouverture de Boss Agent...
echo.
echo  ============================================================
echo            INSTALLATION TERMINEE !
echo  ============================================================
echo.
echo  L'icone "Boss Agent" est sur ton Bureau.
echo  La fenetre s'ouvre dans quelques secondes...
echo.
echo  (Pour les prochaines fois : double-clic sur Boss Agent)
echo  ============================================================
echo.

REM Lancer le Boss directement (pythonw = pas de console noire)
start "" pythonw "%DIR%\boss_launch.pyw"

REM Fermer cette fenetre apres 3 secondes
timeout /t 3 /nobreak >nul
exit
