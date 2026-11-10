# -*- coding: utf-8 -*-
"""
WIRILI LAUNCH (.pyw) — un clic sur l'icône → la fenêtre native de Wirili s'ouvre.

  • Lancé par pythonw.exe (AUCUNE fenêtre console noire).
  • Démarre Streamlit (wirili_app.py) en arrière-plan, port 8502.
  • Attend que le serveur soit prêt (poll localhost:8502).
  • Ouvre une FENÊTRE NATIVE (Edge/Chrome en mode --app=) :
      - pas de barre d'onglets, pas de barre d'URL, pas de menu
      - ressemble à une vraie application desktop
  • Repli : pywebview (Edge WebView2) → navigateur classique.
  • En cas de problème : une boîte de dialogue claire (tkinter) s'affiche.
"""
from __future__ import annotations

import os
import sys
import time
import socket
import subprocess
import webbrowser
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE / "wirili_app.py"
PORT = 8502
URL = f"http://localhost:{PORT}"
LOG = HERE / "wirili_streamlit.log"
MAX_WAIT = 45  # secondes max pour que Streamlit démarre

# Taille de la fenêtre native.
WIN_W = 1280
WIN_H = 820


# --------------------------------------------------------------------------- #
#  Boîte de dialogue (tkinter — toujours disponible avec pythonw)
# --------------------------------------------------------------------------- #
def alert(titre: str, message: str, erreur: bool = False) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        if (HERE / "wirili.ico").exists():
            root.iconbitmap(default=str(HERE / "wirili.ico"))
        if erreur:
            messagebox.showerror(titre, message, parent=root)
        else:
            messagebox.showwarning(titre, message, parent=root)
        root.destroy()
    except Exception:
        print(f"[{titre}] {message}")


def is_port_open(port: int = PORT) -> bool:
    try:
        with socket.create_connection(("localhost", port), timeout=1):
            return True
    except (OSError, ConnectionRefusedError):
        return False


def streamlit_disponible() -> bool:
    return importlib.util.find_spec("streamlit") is not None


# --------------------------------------------------------------------------- #
#  Démarrage
# --------------------------------------------------------------------------- #
def main() -> int:
    # 1. Vérifier que wirili_app.py existe à côté.
    if not APP.exists():
        alert("Wirili — fichier manquant",
              f"Le fichier wirili_app.py est introuvable ici :\n{HERE}\n\n"
              "Réinstalle le raccourci : python install_wirili_shortcut.py",
              erreur=True)
        return 1

    # 2. Vérifier que Streamlit est installé.
    if not streamlit_disponible():
        alert("Wirili — Streamlit absent",
              "La librairie Streamlit n'est pas installée.\n\n"
              "Installe-la avec :\n"
              "    pip install streamlit pillow python-pptx moviepy\n\n"
              "Puis re-clique sur l'icône Wirili.",
              erreur=True)
        return 2

    # 3. Vérifier que agent_pub.py est présent (moteur de Wirili).
    if not (HERE / "agent_pub.py").exists():
        alert("Wirili — moteur absent",
              "Le fichier agent_pub.py (moteur de Wirili) est introuvable.\n\n"
              "Réinstalle : python install_wirili_shortcut.py",
              erreur=True)
        return 1

    # 4. Si le serveur tourne déjà, on ouvre juste la fenêtre native.
    if is_port_open():
        ouvrir_fenetre(URL)
        try:
            while is_port_open():
                time.sleep(2)
        except KeyboardInterrupt:
            pass
        return 0

    # 5. Démarrer Streamlit en arrière-plan (fenêtre cachée, logs en fichier).
    python = sys.executable
    cmd = [python, "-m", "streamlit", "run", str(APP),
           "--server.port", str(PORT),
           "--server.headless", "true",
           "--browser.gatherUsageStats", "false"]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        with open(LOG, "w", encoding="utf-8") as f:
            proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT,
                                    cwd=str(HERE), creationflags=flags)
    except Exception as e:
        alert("Wirili — erreur au démarrage",
              f"Impossible de lancer Streamlit :\n{e}", erreur=True)
        return 3

    # 6. Attendre que le serveur soit prêt.
    for _ in range(MAX_WAIT):
        time.sleep(1)
        if is_port_open():
            break
    else:
        try:
            proc.terminate()
        except Exception:
            pass
        alert("Wirili — démarrage trop long",
              f"Streamlit n'a pas répondu après {MAX_WAIT} s.\n"
              f"Consulte le log :\n{LOG}\n\n"
              "Causes fréquentes : port 8502 occupé, ou erreur de code.",
              erreur=True)
        return 4

    # 7. Ouvrir la fenêtre native.
    ouvrir_fenetre(URL)

    # 8. Garder le lanceur vivant tant que Streamlit tourne.
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    return 0


# --------------------------------------------------------------------------- #
#  Ouverture de la fenêtre native — priorité au mode --app=
# --------------------------------------------------------------------------- #
def ouvrir_fenetre(url: str) -> None:
    """Ouvre Wirili dans une fenêtre native. Essaie dans l'ordre :
       1. Edge/Chrome en mode --app= (vraie fenêtre native, pas de barres)
       2. pywebview (Edge WebView2)
       3. navigateur classique (repli)
    """
    if ouvrir_app_mode(url):
        return
    if ouvrir_pywebview(url):
        return
    if not ouvrir_navigateur(url):
        alert_ouvrir(url)


def _trouver_navigateur_app() -> str | None:
    """Cherche l'exécutable Edge puis Chrome pour le mode --app=."""
    cands: list[Path] = []
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    localappdata = os.environ.get("LOCALAPPDATA", "")
    # Edge (prioritaire : préinstallé sur Win10/11).
    cands += [
        Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(pf86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(localappdata) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    # Chrome.
    cands += [
        Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(pf86) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(localappdata) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for c in cands:
        if c.exists():
            return str(c)
    return None


def ouvrir_app_mode(url: str) -> bool:
    """Ouvre Edge/Chrome en mode --app= : fenêtre native sans barre d'URL."""
    exe = _trouver_navigateur_app()
    if not exe:
        return False
    try:
        args = [
            exe,
            f"--app={url}",
            f"--window-size={WIN_W},{WIN_H}",
            "--window-position=140,60",
            "--no-default-browser-check",
            "--no-first-run",
            "--disable-extensions",
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(args, creationflags=flags)
        return True
    except Exception as e:
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"\n[app-mode ECHEC] {type(e).__name__}: {e}\n")
        except Exception:
            pass
        return False


# --------------------------------------------------------------------------- #
#  pywebview (Edge WebView2) — repli
# --------------------------------------------------------------------------- #
def ouvrir_pywebview(url: str) -> bool:
    """Ouvre Wirili dans une fenêtre native via pywebview."""
    try:
        import webview  # pywebview
    except ImportError:
        return False
    try:
        webview.create_window(
            title="Wirili",
            url=url,
            width=WIN_W,
            height=WIN_H,
            min_size=(900, 600),
            text_select=True,
            confirm_close=False,
        )
        started = False
        for kwargs in (
            {"gui": "edgechromium", "debug": False},
            {"gui": "edgechrom", "debug": False},
            {"debug": False},
        ):
            try:
                webview.start(**kwargs)
                started = True
                break
            except (TypeError, ValueError):
                continue
        if not started:
            webview.start()
        return True
    except Exception as e:
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"\n[pywebview ECHEC] {type(e).__name__}: {e}\n")
        except Exception:
            pass
        return False


# --------------------------------------------------------------------------- #
#  Ouverture robuste du navigateur (dernier recours)
# --------------------------------------------------------------------------- #
def ouvrir_navigateur(url: str) -> bool:
    for i in range(4):
        try:
            ok = webbrowser.open(url, new=2)
            if ok:
                return True
        except Exception:
            pass
        time.sleep(0.8)
    try:
        os.startfile(url)  # type: ignore[attr-defined]
        return True
    except Exception:
        pass
    return False


def alert_ouvrir(url: str) -> None:
    try:
        import tkinter as tk
        root = tk.Tk()
        root.title("Wirili")
        root.geometry("460x180")
        root.resizable(False, False)
        if (HERE / "wirili.ico").exists():
            root.iconbitmap(default=str(HERE / "wirili.ico"))
        tk.Label(root, text="✅ Wirili est prêt !",
                 font=("Segoe UI", 14, "bold")).pack(pady=(18, 6))
        tk.Label(root, text=f"Le serveur tourne sur :\n{url}",
                 font=("Segoe UI", 10)).pack(pady=4)
        def ouvrir():
            try:
                os.startfile(url)  # type: ignore[attr-defined]
            except Exception:
                webbrowser.open(url)
            root.destroy()
        tk.Button(root, text="Ouvrir Wirili", command=ouvrir,
                  font=("Segoe UI", 11, "bold"), width=18, height=1,
                  bg="#7C3AED", fg="white", relief="flat").pack(pady=12)
        root.mainloop()
    except Exception:
        alert("Wirili — prêt",
              f"Wirili est prêt. Ouvre manuellement :\n{url}")


if __name__ == "__main__":
    sys.exit(main())
