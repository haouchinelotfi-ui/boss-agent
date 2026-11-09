# -*- coding: utf-8 -*-
"""
Crée une icône Boss Agent sur le Bureau :
  1. génère un .ico (cerveau stylisé sur dégradé bleu nuit → cyan)
  2. copie boss_agent.py, boss_app.py, agent_pub.py dans un dossier stable
  3. configure les credentials Streamlit (évite le prompt email)
  4. crée le raccourci .lnk sur le Bureau

Lancement : python install_boss_shortcut.py
Dépendance : pip install pillow
"""
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw  # type: ignore

# --------------------------------------------------------------------------- #
#  1. ICÔNE
# --------------------------------------------------------------------------- #
ICON_SIZES = [256, 128, 64, 48, 32, 16]
HERE = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(HERE, "boss.ico")


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
    """Dessine un cerveau stylisé (boss/IA) — deux hémisphères bombés + sillons."""
    d = ImageDraw.Draw(img)
    s = img.size[0]
    cx = s * 0.50
    white = (255, 255, 255, 255)
    soft = (235, 245, 255, 255)
    line = (180, 210, 240, 255)
    wl = max(2, int(s * 0.016))

    # --- Tête/cerveau : grande forme arrondie ---
    bw = s * 0.34   # demi-largeur
    bt = s * 0.18   # haut
    bb = s * 0.74   # bas
    d.ellipse([cx - bw, bt, cx + bw, bb], fill=white, outline=soft, width=wl)

    # --- Séparation centrale (sillon longitudinal) ---
    d.line([cx, bt + s * 0.04, cx, bb - s * 0.04], fill=line, width=wl)

    # --- Sillons gauches ---
    for frac, dy in [(0.30, -0.02), (0.52, 0.0), (0.72, 0.02)]:
        yy = bt + (bb - bt) * frac
        d.arc([cx - bw, yy - s * 0.05, cx, yy + s * 0.05],
              start=90, end=270, fill=line, width=wl)
    # --- Sillons droits ---
    for frac, dy in [(0.30, -0.02), (0.52, 0.0), (0.72, 0.02)]:
        yy = bt + (bb - bt) * frac
        d.arc([cx, yy - s * 0.05, cx + bw, yy + s * 0.05],
              start=270, end=90, fill=line, width=wl)

    # --- Couronne de boss (3 pointes dorées au-dessus) ---
    gold = (245, 200, 90, 255)
    gold_dark = (210, 160, 50, 255)
    cw = s * 0.04   # demi-base d'une pointe
    ct = s * 0.06   # sommet d'une pointe
    cb = s * 0.16   # base de la couronne
    # bandeau
    d.rounded_rectangle([cx - bw * 0.95, cb, cx + bw * 0.95, cb + s * 0.05],
                        radius=s * 0.015, fill=gold, outline=gold_dark, width=wl)
    # 3 pointes
    for off in (-bw * 0.6, 0, bw * 0.6):
        d.polygon([(cx + off - cw, cb), (cx + off + cw, cb), (cx + off, ct)],
                  fill=gold, outline=gold_dark)
        # bijou sur la pointe
        d.ellipse([cx + off - cw * 0.5, cb - s * 0.015,
                   cx + off + cw * 0.5, cb + s * 0.035], fill=(255, 255, 255, 255))


images = []
for sz in ICON_SIZES:
    im = rounded_gradient(sz, (12, 28, 58), (30, 130, 180))  # bleu nuit -> cyan
    draw_logo(im)
    images.append(im)

images[0].save(ICON_PATH, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
print(f"[OK] Icône créée : {ICON_PATH}")

# --------------------------------------------------------------------------- #
#  2. DOSSIER STABLE + COPIE DES SCRIPTS
# --------------------------------------------------------------------------- #
STABLE_DIR = os.path.join(os.path.expanduser("~"), "boss_agent")
os.makedirs(STABLE_DIR, exist_ok=True)

for fname in ("boss_agent.py", "boss_app.py", "agent_pub.py"):
    src = os.path.join(HERE, fname)
    dst = os.path.join(STABLE_DIR, fname)
    if os.path.exists(src):
        shutil.copy2(src, dst)
        print(f"[OK] Copié : {dst}")
    else:
        print(f"[!] Manquant (ignoré) : {src}")

# icône dans le dossier stable
ICON_DST = os.path.join(STABLE_DIR, "boss.ico")
shutil.copy2(ICON_PATH, ICON_DST)

# --------------------------------------------------------------------------- #
#  3. CREDENTIALS STREAMLIT (évite le prompt email)
# --------------------------------------------------------------------------- #
home = os.path.expanduser("~")
streamlit_cfg_dir = os.path.join(home, ".streamlit")
os.makedirs(streamlit_cfg_dir, exist_ok=True)
creds_path = os.path.join(streamlit_cfg_dir, "credentials.toml")
# ne pas écraser si déjà configuré avec une vraie email
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
lnk_path = os.path.join(desktop, "Boss Agent.lnk")
app_script = os.path.join(STABLE_DIR, "boss_app.py")

# Lance Streamlit (ouvre le navigateur auto), port 8501
ps = f'''
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("{lnk_path}")
$sc.TargetPath = "{python_exe}"
$sc.Arguments = '-m streamlit run "{app_script}" --server.port 8501'
$sc.WorkingDirectory = "{STABLE_DIR}"
$sc.IconLocation = "{ICON_DST},0"
$sc.Description = "Boss Agent - Manager autonome (FreeLLMAPI local)"
$sc.WindowStyle = 7
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

print("\n✅ Terminé. Double-clique sur « Boss Agent » sur le Bureau.")
print("   Streamlit s'ouvre sur http://localhost:8501")
print("   (FreeLLMAPI doit tourner sur 127.0.0.1:31415)")
