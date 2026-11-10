# -*- coding: utf-8 -*-
"""
Crée une icône Wirili sur le Bureau :
  1. génère un .ico ( « W » stylisé sur dégradé violet → rose )
  2. copie wirili_app.py, wirili_launch.pyw, agent_pub.py dans un dossier stable
  3. configure les credentials Streamlit (évite le prompt email)
  4. crée le raccourci .lnk sur le Bureau

Lancement : python install_wirili_shortcut.py
Dépendance : pip install pillow
"""
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont  # type: ignore

# --------------------------------------------------------------------------- #
#  1. ICÔNE
# --------------------------------------------------------------------------- #
ICON_SIZES = [256, 128, 64, 48, 32, 16]
HERE = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(HERE, "wirili.ico")


def rounded_gradient(size, c1, c2):
    """Dégradé vertical c1 -> c2 dans un carré arrondi."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    for y in range(size):
        r = int(c1[0] + (c2[0] - c1[0]) * y / max(size - 1, 1))
        g = int(c1[1] + (c2[1] - c1[1]) * y / max(size - 1, 1))
        b = int(c1[2] + (c2[2] - c1[2]) * y / max(size - 1, 1))
        for x in range(size):
            px[x, y] = (r, g, b, 255)
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, size - 1, size - 1],
                         radius=int(size * 0.22), fill=255)
    rounded = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rounded.paste(img, (0, 0), mask)
    return rounded


def draw_logo(img):
    """Dessine un « W » stylisé (Wirili) en blanc, centré."""
    d = ImageDraw.Draw(img)
    s = img.size[0]
    white = (255, 255, 255, 255)
    shadow = (124, 58, 237, 90)  # violet doux pour l'ombre

    # Police grasse. DejaVuSans est bundlée avec Pillow.
    font = None
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "arialbd.ttf",
                 "arial.ttf"):
        try:
            font = ImageFont.truetype(name, int(s * 0.62))
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    # Mesurer le W pour le centrer.
    text = "W"
    try:
        bbox = d.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (s - tw) / 2 - bbox[0]
        ty = (s - th) / 2 - bbox[1] - int(s * 0.02)
    except Exception:
        tx, ty = s * 0.22, s * 0.18

    # Ombre légère (décalage bas-droite).
    d.text((tx + max(1, int(s * 0.018)), ty + max(1, int(s * 0.018))),
           text, font=font, fill=shadow)
    # W principal.
    d.text((tx, ty), text, font=font, fill=white)


images = []
for sz in ICON_SIZES:
    im = rounded_gradient(sz, (124, 58, 237), (219, 39, 119))  # violet -> rose
    draw_logo(im)
    images.append(im)

images[0].save(ICON_PATH, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
print(f"[OK] Icône créée : {ICON_PATH}")

# --------------------------------------------------------------------------- #
#  2. DOSSIER STABLE + COPIE DES SCRIPTS
# --------------------------------------------------------------------------- #
STABLE_DIR = os.path.join(os.path.expanduser("~"), "wirili")
os.makedirs(STABLE_DIR, exist_ok=True)

verrouilles = []
for fname in ("wirili_app.py", "wirili_launch.pyw", "agent_pub.py"):
    src = os.path.join(HERE, fname)
    dst = os.path.join(STABLE_DIR, fname)
    if os.path.exists(src):
        try:
            shutil.copy2(src, dst)
            print(f"[OK] Copié : {dst}")
        except PermissionError:
            verrouilles.append(fname)
            print(f"[!] Verrouillé (saute) : {fname} — ferme Wirili et relance.")
    else:
        print(f"[!] Manquant (ignoré) : {src}")

# icône dans le dossier stable.
ICON_DST = os.path.join(STABLE_DIR, "wirili.ico")
try:
    shutil.copy2(ICON_PATH, ICON_DST)
except PermissionError:
    print("[!] wirili.ico verrouillé — icône existante conservée.")

if verrouilles:
    print("\n[!] Certains fichiers étaient verrouillés (Wirili tourne encore).")
    print("    1. Ferme Wirili : ferme la fenêtre / tue le processus")
    print("    2. Relance : python install_wirili_shortcut.py")

# --------------------------------------------------------------------------- #
#  3. CREDENTIALS STREAMLIT (évite le prompt email)
# --------------------------------------------------------------------------- #
home = os.path.expanduser("~")
streamlit_cfg_dir = os.path.join(home, ".streamlit")
os.makedirs(streamlit_cfg_dir, exist_ok=True)
creds_path = os.path.join(streamlit_cfg_dir, "credentials.toml")
need_write = True
if os.path.exists(creds_path):
    try:
        with open(creds_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "email" in content and 'email = ""' not in content:
            need_write = False
    except Exception:
        pass
if need_write:
    with open(creds_path, "w", encoding="utf-8") as f:
        f.write("[general]\nemail = \"\"\n")
    print(f"[OK] Credentials Streamlit : {creds_path}")

# --------------------------------------------------------------------------- #
#  4. RACCOURCI SUR LE BUREAU
# --------------------------------------------------------------------------- #
python_exe = sys.executable
desktop = os.path.join(os.path.expanduser("~"), "Desktop")
lnk_path = os.path.join(desktop, "Wirili.lnk")

# Lance le .pyw via pythonw.exe (AUCUNE console noire) → fenêtre directe.
pythonw = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
if not os.path.exists(pythonw):
    pythonw = python_exe  # repli (rare : pythonw absent)
launch_script = os.path.join(STABLE_DIR, "wirili_launch.pyw")
ps = f'''
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("{lnk_path}")
$sc.TargetPath = "{pythonw}"
$sc.Arguments = '"{launch_script}"'
$sc.WorkingDirectory = "{STABLE_DIR}"
$sc.IconLocation = "{ICON_DST},0"
$sc.Description = "Wirili - Agent publicitaire autonome"
$sc.WindowStyle = 1
$sc.Save()
Write-Output "Shortcut created"
'''
r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, text=True)
print(r.stdout.strip())
if r.returncode != 0:
    print("PS STDERR:", r.stderr.strip())
else:
    print(f"[OK] Raccourci créé : {lnk_path}")

print("\n✅ Terminé. Double-clique sur « Wirili » sur le Bureau.")
print("   → La fenêtre de Wirili s'ouvre DIRECTEMENT (pas de console noire).")
print("   → Serveur sur http://localhost:8502")
print("   (Le Boss Agent peut tourner en même temps sur le port 8501.)")
