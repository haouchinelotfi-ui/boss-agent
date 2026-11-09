# -*- coding: utf-8 -*-
"""
SETUP TELEGRAM - configure le bot en 2 minutes, sans friction.

Étapes :
  1. Tu crées le bot via @BotFather (le script t'ouvre Telegram).
  2. Tu colles le token ici.
  3. Le script valide le token (getMe), le sauvegarde dans .env.
  4. Il lance boss_telegram.py automatiquement.

Lancement : python setup_telegram.py

Si tu as déjà un token : set BOSS_TELEGRAM_TOKEN=...  puis python setup_telegram.py
"""
from __future__ import annotations

import os
import sys
import subprocess
import webbrowser
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

try:
    import requests
except ImportError:
    print("Installation de requests...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "requests"], check=True)
    import requests

ENV_FILE = Path(__file__).parent / ".env"
BOTFATHER_URL = "https://t.me/BotFather"
USERINFOBOT_URL = "https://t.me/userinfobot"


def banner(t: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {t}")
    print("=" * 60)


def get_token() -> str:
    """Demande et valide un token Telegram."""
    # Token déjà en env ?
    token = os.environ.get("BOSS_TELEGRAM_TOKEN", "").strip()
    if token:
        print(f"✅ Token trouvé dans l'environnement.")
        return token

    # Token déjà dans .env ?
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("BOSS_TELEGRAM_TOKEN="):
                token = line.split("=", 1)[1].strip()
                if token:
                    print(f"✅ Token trouvé dans .env")
                    return token

    banner("ÉTAPE 1/3 — Créer le bot via @BotFather")
    print("""
Ouvre Telegram, va sur @BotFather (https://t.me/BotFather), puis :
  1. Envoie :  /newbot
  2. Donne un nom (ex : Boss Agent)
  3. Donne un username se terminant par 'bot' (ex : boss_agent_local_bot)
  4. BotFather te renvoie un token du type :
        123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

Je t'ouvre Telegram dans le navigateur maintenant.
""")
    try:
        webbrowser.open(BOTFATHER_URL)
        print("→ Telegram ouvert dans le navigateur.")
    except Exception:
        print(f"(Ouvre manuellement : {BOTFATHER_URL})")

    banner("ÉTAPE 2/3 — Colle ton token")
    while True:
        token = input("\nColle le token de BotFather : ").strip()
        if not token:
            print("Token vide. Réessaie ou Ctrl+C pour quitter.")
            continue
        # Validation via l'API Telegram (getMe).
        print("Validation du token...")
        try:
            r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
            data = r.json()
            if data.get("ok"):
                me = data["result"]
                print(f"\n✅ Bot valide : @{me.get('username')} ({me.get('first_name')})")
                return token
            else:
                desc = data.get("description", "?")
                print(f"❌ Token invalide : {desc}")
                print("Réessaie avec le bon token.")
        except requests.RequestException as e:
            print(f"⚠️ Pas de réseau ({e}). Vérifie ta connexion puis réessaie.")


def get_admin_id() -> str:
    """Demande (optionnel) l'ID Telegram admin pour /stop."""
    banner("ÉTAPE 3/3 — (Optionnel) ID admin pour /stop")
    print(f"""
Pour réserver la commande /stop à toi seul, j'ai besoin de ton ID Telegram.

Récupère-le via @userinfobot (https://t.me/userinfobot) :
  1. Ouvre le lien, envoie n'importe quoi,
  2. Il te répond avec ton 'Id: 123456789'.

Sinon, appuie juste sur Entrée (tout le monde pourra /stop).
""")
    try:
        webbrowser.open(USERINFOBOT_URL)
    except Exception:
        pass
    return input("Ton ID Telegram (ou Entrée pour ignorer) : ").strip()


def save_env(token: str, admin_id: str) -> None:
    """Sauvegarde dans .env (ignoré par git)."""
    lines = [f"BOSS_TELEGRAM_TOKEN={token}"]
    if admin_id:
        lines.append(f"BOSS_ADMIN_IDS={admin_id}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n💾 Configuration sauvegardée dans {ENV_FILE.name}")
    print("   (Ce fichier est ignoré par git — ton token reste privé.)")


def launch_bot() -> None:
    """Lance boss_telegram.py avec les variables d'env chargées."""
    banner("LANCEMENT DU BOT")
    print("""
Le bot va maintenant écouter Telegram. Tu peux :
  - depuis ton téléphone, envoyer /start au bot pour voir l'aide,
  - lancer une mission :  /mission Prépare 3 posts LinkedIn...
  - arrêter : Ctrl+C ici, ou /stop depuis Telegram (si admin).

Appuie sur Entrée pour lancer, ou Ctrl+C pour quitter sans lancer.
""")
    try:
        input()
    except KeyboardInterrupt:
        print("\nBot non lancé. Relance plus tard : python boss_telegram.py")
        return

    # Recharger .env dans l'environnement du sous-processus.
    env = os.environ.copy()
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

    cmd = [sys.executable, "boss_telegram.py"]
    print(f"$ {' '.join(cmd)}\n")
    subprocess.run(cmd, env=env, cwd=str(Path(__file__).parent))


def main() -> None:
    banner("BOSS AGENT — Configuration Telegram")
    print("""
Ce script configure le bot Telegram en 3 étapes :
  1. Créer le bot via @BotFather
  2. Coller + valider le token
  3. (Option) Récupérer ton ID admin

Avantage Telegram : tu pilotes le Boss depuis ton téléphone
N'IMPORTE OÙ (Internet), sans être sur le même Wi-Fi que le PC.
""")
    try:
        token = get_token()
        admin_id = get_admin_id()
        save_env(token, admin_id)
        launch_bot()
    except KeyboardInterrupt:
        print("\n\nConfiguration interrompue. Relance : python setup_telegram.py")


if __name__ == "__main__":
    main()
