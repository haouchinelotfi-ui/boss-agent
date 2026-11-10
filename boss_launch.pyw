# -*- coding: utf-8 -*-
"""
BOSS LAUNCH (.pyw) — un clic sur l'icône → la fenêtre native du Boss s'ouvre.

  • Lancé par pythonw.exe (AUCUNE fenêtre console noire).
  • Démarre Streamlit en arrière-plan (processus caché).
  • Attend que le serveur soit prêt (poll localhost:8501).
  • Ouvre une FENÊTRE NATIVE (pywebview / Edge WebView2) — pas de Chrome.
  • Repli navigateur si pywebview absent.
  • En cas de problème : une boîte de dialogue claire (tkinter) s'affiche,
    pas de console.
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
APP = HERE / "boss_app.py"
PORT = 8501
URL = f"http://localhost:{PORT}"
LOG = HERE / "boss_streamlit.log"
MAX_WAIT = 45  # secondes max pour que Streamlit démarre


# --------------------------------------------------------------------------- #
#  Boîte de dialogue (tkinter — toujours disponible avec pythonw)
# --------------------------------------------------------------------------- #
def alert(titre: str, message: str, erreur: bool = False) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        root.iconbitmap(default=str(HERE / "boss.ico")) if (HERE / "boss.ico").exists() else None
        if erreur:
            messagebox.showerror(titre, message, parent=root)
        else:
            messagebox.showwarning(titre, message, parent=root)
        root.destroy()
    except Exception:
        # Dernier recours : console (ne devrait jamais arriver avec pythonw)
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
    # 1. Vérifier que boss_app.py existe à côté.
    if not APP.exists():
        alert("Boss Agent — fichier manquant",
              f"Le fichier boss_app.py est introuvable ici :\n{HERE}\n\n"
              "Réinstalle le raccourci : python install_boss_shortcut.py",
              erreur=True)
        return 1

    # 2. Vérifier que Streamlit est installé.
    if not streamlit_disponible():
        alert("Boss Agent — Streamlit absent",
              "La librairie Streamlit n'est pas installée.\n\n"
              "Installe-la avec :\n"
              "    pip install streamlit pillow python-pptx\n\n"
              "Puis re-clique sur l'icône Boss.",
              erreur=True)
        return 2

    # 3. Si le serveur tourne déjà, on ouvre juste le navigateur.
    if is_port_open():
        webbrowser.open(URL)
        return 0

    # 4. Démarrer Streamlit en arrière-plan (fenêtre cachée, logs en fichier).
    python = sys.executable
    cmd = [python, "-m", "streamlit", "run", str(APP),
           "--server.port", str(PORT),
           "--server.headless", "true",
           "--browser.gatherUsageStats", "false"]
    # CREATE_NO_WINDOW = pas de console sous Windows.
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        with open(LOG, "w", encoding="utf-8") as f:
            proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT,
                                    cwd=str(HERE), creationflags=flags)
    except Exception as e:
        alert("Boss Agent — erreur au démarrage",
              f"Impossible de lancer Streamlit :\n{e}", erreur=True)
        return 3

    # 5. Attendre que le serveur soit prêt.
    for _ in range(MAX_WAIT):
        time.sleep(1)
        if is_port_open():
            break
    else:
        # Streamlit n'a pas démarré à temps.
        try:
            proc.terminate()
        except Exception:
            pass
        alert("Boss Agent — démarrage trop long",
              f"Streamlit n'a pas répondu après {MAX_WAIT} s.\n"
              f"Consulte le log :\n{LOG}\n\n"
              "Causes fréquentes : port 8501 occupé, ou erreur de code.",
              erreur=True)
        return 4

    # 6. Ouvrir une FENÊTRE NATIVE (pywebview) — pas de Chrome.
    #    Si pywebview absent → repli navigateur classique.
    if not ouvrir_fenetre_native(URL):
        if not ouvrir_navigateur(URL):
            alert_ouvrir(URL)

    # 7. Garder le lanceur vivant tant que Streamlit tourne (pour que
    #    l icone de la barre des taches reste presente). Quand l utilisateur
    #    ferme Streamlit (Ctrl+C ou arret), le lanceur se termine proprement.
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    return 0


# --------------------------------------------------------------------------- #
#  Fenêtre native (pywebview / Edge WebView2) — pas de Chrome
# --------------------------------------------------------------------------- #
def ouvrir_fenetre_native(url: str) -> bool:
    """Ouvre le Boss dans une vraie fenêtre desktop native via pywebview.
    Retourne False si pywebview n'est pas disponible (repli navigateur)."""
    try:
        import webview  # pywebview
    except ImportError:
        return False

    try:
        # Fenêtre native : titre, taille, icône, pas de barre Chrome.
        window = webview.create_window(
            title="Boss Agent",
            url=url,
            width=1280,
            height=820,
            min_size=(900, 600),
            text_select=True,
            confirm_close=False,
        )
        # Activer EdgeChromium (WebView2) sur Windows si dispo.
        try:
            webview.start(gui_edge=True, debug=False)  # type: ignore[call-arg]
        except TypeError:
            webview.start(debug=False)
        return True
    except Exception as e:
        # pywebview présent mais erreur → on tente quand même le navigateur.
        try:
            alert("Boss Agent — fenêtre native échouée",
                  f"pywebview a échoué : {e}\n\nOuverture dans le navigateur.")
        except Exception:
            pass
        return False


# --------------------------------------------------------------------------- #
#  Ouverture robuste du navigateur (pythonw peut faire echouer webbrowser)
# --------------------------------------------------------------------------- #
def ouvrir_navigateur(url: str) -> bool:
    """Tente d ouvrir le navigateur par plusieurs methodes."""
    # Methode 1 : webbrowser.open, plusieurs essais etcarts.
    for i in range(4):
        try:
            ok = webbrowser.open(url, new=2)
            if ok:
                return True
        except Exception:
            pass
        time.sleep(0.8)
    # Methode 2 : os.startfile (Windows) — equivalent a un double-clic sur l URL.
    try:
        os.startfile(url)  # type: ignore[attr-defined]
        return True
    except Exception:
        pass
    return False


def alert_ouvrir(url: str) -> None:
    """Le Boss est pret mais le navigateur ne s est pas ouvert : on propose
    un bouton pour l ouvrir manuellement."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.title("Boss Agent")
        root.geometry("460x180")
        root.resizable(False, False)
        if (HERE / "boss.ico").exists():
            root.iconbitmap(default=str(HERE / "boss.ico"))
        tk.Label(root, text="✅ Le Boss est pret !",
                 font=("Segoe UI", 14, "bold")).pack(pady=(18, 6))
        tk.Label(root, text=f"Le serveur tourne sur :\n{url}",
                 font=("Segoe UI", 10)).pack(pady=4)
        def ouvrir():
            try:
                os.startfile(url)  # type: ignore[attr-defined]
            except Exception:
                webbrowser.open(url)
            root.destroy()
        tk.Button(root, text="Ouvrir le Boss", command=ouvrir,
                  font=("Segoe UI", 11, "bold"), width=18, height=1,
                  bg="#4CAF50", fg="white", relief="flat").pack(pady=12)
        root.mainloop()
    except Exception:
        # Dernier recours : alerte simple.
        alert("Boss Agent — pret",
              f"Le Boss est pret. Ouvre manuellement :\n{url}")


if __name__ == "__main__":
    sys.exit(main())
