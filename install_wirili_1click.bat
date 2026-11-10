@echo off
chcp 65001 >nul
title Installation de Wirili
color 0B

echo.
echo  ============================================================
echo                INSTALLATION DE WIRILI  (1-CLIC)
echo  ============================================================
echo.

REM Dossier d'installation
set "DIR=%USERPROFILE%\WIRILI"
if not exist "%DIR%" mkdir "%DIR%"
cd /d "%DIR%"

echo  [1/5] Telechargement des fichiers...
powershell -NoProfile -Command "$t=[DateTime]::Now.Ticks; $u='https://raw.githubusercontent.com/haouchinelotfi-ui/boss-agent/main'; Invoke-WebRequest (\"$u/install_wirili_shortcut.py?t=$t\") -OutFile install_wirili_shortcut.py; Invoke-WebRequest (\"$u/wirili_app.py?t=$t\") -OutFile wirili_app.py; Invoke-WebRequest (\"$u/wirili_launch.pyw?t=$t\") -OutFile wirili_launch.pyw; Invoke-WebRequest (\"$u/agent_pub.py?t=$t\") -OutFile agent_pub.py"

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
  pip install streamlit pillow python-pptx moviepy -q
)
echo  [OK] Streamlit pret.
echo.

echo  [4/5] Creation de l'icone + raccourci Bureau...
python install_wirili_shortcut.py
echo.

echo  [5/5] Ouverture de Wirili...
echo.
echo  ============================================================
echo            INSTALLATION TERMINEE !
echo  ============================================================
echo.
echo  L'icone "Wirili" est sur ton Bureau.
echo  La fenetre s'ouvre dans quelques secondes...
echo.
echo  (Pour les prochaines fois : double-clic sur Wirili)
echo  ============================================================
echo.

REM Lancer Wirili directement (pythonw = pas de console noire)
start "" pythonw "%DIR%\wirili_launch.pyw"

REM Fermer cette fenetre apres 3 secondes
timeout /t 3 /nobreak >nul
exit
