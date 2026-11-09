# -*- coding: utf-8 -*-
"""
BOSS TELEGRAM - pilote le Boss Agent depuis Telegram (depuis ton téléphone, sans Wi-Fi partagé).

Tourne en LOCAL sous FreeLLMAPI (http://127.0.0.1:31415). Aucune clé Anthropic.
Le bot Telegram a juste besoin d'un token (créé via @BotFather).

Installation : pip install requests python-telegram-bot==21.6
              (boss_agent.py, boss_app.py, agent_pub.py dans le même dossier)

Lancement    : python boss_telegram.py
              (positionne BOSS_TELEGRAM_TOKEN=<token> ou réponds à la question)

Commandes Telegram :
  /start            → aide
  /mission <texte>  → lance le Boss sur la mission
  /sante            → contrôle de santé du moteur LLM local
  /run              → dossier du dernier run
  /stop             → arrête le bot (admin uniquement)

L'avantage vs Streamlit : Telegram passe par Internet, donc tu pilotes le Boss
depuis ton téléphone n'importe où, sans être sur le même Wi-Fi que le PC.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

# Forcer UTF-8 sur Windows (cp1252 casse l'envoi de messages accentués à Telegram).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

try:
    import requests
except ImportError:
    print("Installe requests :  pip install requests")
    raise

# boss_agent / agent_pub / boss_app sont dans le même dossier.
sys.path.insert(0, str(Path(__file__).parent))

from boss_agent import Boss, LLM
from boss_app import build_boss  # réutilise le branchement agent publicité

TOKEN = os.environ.get("BOSS_TELEGRAM_TOKEN", "").strip()
ADMIN_IDS = {int(x) for x in os.environ.get("BOSS_ADMIN_IDS", "").split(",") if x.strip().isdigit()}
BRAND_DEFAULT = os.environ.get("BOSS_BRAND", "Lumina Glow")

# État global du dernier run (partagé entre les threads).
_last_run: dict = {"run_dir": None, "mission": None, "statut": None}
_lock = threading.Lock()


# --------------------------------------------------------------------------- #
#  API Telegram (HTTP REST — pas de SDK lourd, juste requests)
# --------------------------------------------------------------------------- #
def tg(method: str, **payload):
    """Appelle l'API Bot Telegram. Retourne le JSON ou lève."""
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    r = requests.post(url, json=payload, timeout=30)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
    return data.get("result", {})


def send(chat_id: int, text: str, reply_to: int | None = None) -> None:
    """Envoie un message en le découpant si > 4000 caractères (limite Telegram 4096)."""
    text = text or "(vide)"
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
    for c in chunks:
        tg("sendMessage", chat_id=chat_id, text=c,
           parse_mode="HTML", disable_web_page_preview=True,
           reply_to_message_id=reply_to)
        time.sleep(0.3)  # anti flood (30 msg/s max)


def send_doc(chat_id: int, path: Path, caption: str = "") -> None:
    """Envoie un fichier (livrable) en pièce jointe."""
    if not path.exists():
        send(chat_id, f"⚠️ Fichier introuvable : {path}")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    with open(path, "rb") as f:
        r = requests.post(url, data={"chat_id": chat_id, "caption": caption[:1000]},
                          files={"document": f}, timeout=60)
    if not r.json().get("ok"):
        send(chat_id, f"⚠️ Envoi fichier échoué : {r.json().get('description')}")


# --------------------------------------------------------------------------- #
#  Exécution du Boss (en arrière-plan pour ne pas bloquer le polling)
# --------------------------------------------------------------------------- #
def run_boss_async(chat_id: int, mission: str, allow: bool, brand: str) -> None:
    """Lance le Boss dans un thread séparé et notifie Telegram à chaque étape."""
    try:
        send(chat_id, "🧠 <b>Boss lancé</b>\n<i>Planification en cours via FreeLLMAPI local…</i>")
        boss = build_boss(allow_irreversible=allow, brand_name=brand)

        # Vérification de santé avant de lancer.
        health = boss.doctor.health_check(boss.llm)
        if not health.get("llm"):
            provs = health.get("providers", [])
            lignes = ["❌ Aucun provider LLM disponible."]
            for p in provs:
                mark = "✅" if p.get("etat") == "ok" else "❌"
                lignes.append(f"  {mark} <code>{p['name']}</code> ({p.get('model','?')}) — {p.get('etat','?')}")
            lignes.append("Configure un fallback (GEMINI_API_KEY, GROQ_API_KEY…) ou relance FreeLLMAPI.")
            send(chat_id, "\n".join(lignes))
            return

        t0 = time.time()
        report = boss.run(mission)
        duree = time.time() - t0

        with _lock:
            _last_run["run_dir"] = str(boss.run_dir)
            _last_run["mission"] = mission
            _last_run["statut"] = report.get("statut")

        # Résumé
        emoji = "✅" if report.get("statut") == "complet" else "⚠️"
        lignes = [f"{emoji} <b>Mission terminée</b> ({duree:.0f}s) — statut : {report.get('statut')}",
                  f"📁 Run : <code>{boss.run_dir}</code>"]

        taches = report.get("taches", {})
        lignes.append(f"\n📋 <b>{len(taches)} tâche(s)</b>")
        for tid, t in taches.items():
            mark = {"done": "✅", "escalated": "🆘"}.get(t["statut"], "❓")
            lignes.append(f"  {mark} <code>{tid}</code> · {t['role']} · {t['essais']} essai(s)")

        if report.get("a_traiter_par_humain"):
            lignes.append("\n🆘 <b>À traiter par humain :</b> " + ", ".join(report["a_traiter_par_humain"]))

        if report.get("incidents"):
            lignes.append(f"\n🩺 {len(report['incidents'])} intervention(s) du docteur (voir /run pour détails).")

        send(chat_id, "\n".join(lignes))

        # Envoi des livrables (textes courts en message, fichiers en pièce jointe).
        livrables = report.get("livrables", [])
        if livrables:
            send(chat_id, f"📦 <b>{len(livrables)} livrable(s)</b> — envoi en cours…")
            for item in livrables:
                p = Path(item)
                if p.is_dir():
                    for f in sorted(p.iterdir()):
                        if f.is_file() and f.stat().st_size < 45_000_000:  # 45 Mo max Telegram
                            send_doc(chat_id, f, f"📎 {f.name}")
                elif p.is_file() and p.stat().st_size < 45_000_000:
                    send_doc(chat_id, p, f"📎 {p.name}")
        else:
            send(chat_id, "ℹ️ Aucun livrable produit.")

    except Exception as e:
        send(chat_id, f"❌ <b>Erreur Boss</b>\n<code>{type(e).__name__}: {e}</code>")


# --------------------------------------------------------------------------- #
#  Commandes
# --------------------------------------------------------------------------- #
def cmd_help(chat_id: int) -> None:
    send(chat_id,
         "🧠 <b>Boss Agent</b> — pilote local (FreeLLMAPI)\n\n"
         "<b>/mission</b> &lt;texte&gt; — lance une mission (posts, slides, code, données…)\n"
         "<b>/sante</b> — contrôle de santé du moteur LLM local\n"
         "<b>/run</b> — dossier du dernier run\n"
         "<b>/allow</b> — active les actions irréversibles (désactivées par défaut)\n"
         "<b>/brand</b> &lt;nom&gt; — change la marque (agent publicité)\n"
         "<b>/stop</b> — arrête le bot (admin)\n\n"
         "<i>Exemple :</i>\n"
         "<code>/mission Prépare posts LinkedIn + Instagram + slides pour le lancement de la crème visage</code>")


def cmd_health(chat_id: int) -> None:
    try:
        llm = LLM()
        import boss_agent
        d = boss_agent.Doctor(boss_agent.Audit(Path("runs/_tg_health")), None, Path("runs/_tg_health"))
        health = d.health_check(llm)
        lignes = ["🩺 <b>Contrôle de santé</b>"]
        lignes.append(f"  {'✅' if health.get('disque') else '❌'} <code>disque</code>")
        lignes.append(f"  {'✅' if health.get('llm') else '❌'} <code>llm</code> — actif : <b>{health.get('llm_mode','?')}</b>")
        for p in health.get("providers", []):
            mark = "✅" if p.get("etat") == "ok" else ("⏳" if p.get("etat") == "cooldown" else "⚪")
            lignes.append(f"  {mark} <code>{p['name']}</code> ({p.get('model','?')}) — {p.get('etat','?')}")
        send(chat_id, "\n".join(lignes))
    except Exception as e:
        send(chat_id, f"❌ Contrôle impossible : {e}")


def cmd_run(chat_id: int) -> None:
    with _lock:
        rd = _last_run.get("run_dir")
    if not rd:
        send(chat_id, "ℹ️ Aucun run encore. Lance une mission avec /mission.")
        return
    send(chat_id, f"📁 Dernier run : <code>{rd}</code>")
    # Essaye d'envoyer le rapport.json si présent.
    rapport = Path(rd) / "rapport.json"
    if rapport.exists():
        send_doc(chat_id, rapport, "rapport.json")


# --------------------------------------------------------------------------- #
#  Polling long (getUpdates) — pas de webhook, marche derrière box/moins de config
# --------------------------------------------------------------------------- #
def main() -> None:
    global TOKEN
    if not TOKEN:
        TOKEN = input("Colle ton token Telegram (via @BotFather) : ").strip()
        if not TOKEN:
            print("Token requis. Relance avec BOSS_TELEGRAM_TOKEN=<token> python boss_telegram.py")
            return

    # Vérifie le token.
    try:
        me = tg("getMe")
        print(f"✅ Bot connecté : @{me.get('username')} ({me.get('first_name')})")
    except Exception as e:
        print(f"❌ Token invalide : {e}")
        return

    # État session.
    state = {"allow": False, "brand": BRAND_DEFAULT}

    # Récupère l'offset pour ne pas rejouer les anciens messages.
    offset = None
    print("Polling Telegram… (Ctrl+C pour arrêter)")

    while True:
        try:
            params = {"timeout": 25}
            if offset:
                params["offset"] = offset
            r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                             params=params, timeout=35)
            data = r.json()
            if not data.get("ok"):
                print("getUpdates error:", data)
                time.sleep(3)
                continue

            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message")
                if not msg:
                    continue
                chat_id = msg["chat"]["id"]
                user_id = msg["from"]["id"]
                text = (msg.get("text") or "").strip()
                if not text:
                    continue

                print(f"  [{chat_id}] {msg['from'].get('first_name')}: {text[:60]}")

                # Commandes.
                if text.startswith("/start"):
                    cmd_help(chat_id)
                elif text.startswith("/mission"):
                    mission = text[len("/mission"):].strip()
                    if not mission:
                        send(chat_id, "❌ Donne une mission : <code>/mission Prépare 3 posts LinkedIn…</code>")
                    else:
                        send(chat_id, f"🚀 Mission reçue. Marque : <b>{state['brand']}</b>. "
                                      f"Irréversible : {'oui' if state['allow'] else 'non'}.")
                        t = threading.Thread(target=run_boss_async,
                                             args=(chat_id, mission, state["allow"], state["brand"]),
                                             daemon=True)
                        t.start()
                elif text.startswith("/sante"):
                    cmd_health(chat_id)
                elif text.startswith("/run"):
                    cmd_run(chat_id)
                elif text.startswith("/allow"):
                    state["allow"] = not state["allow"]
                    send(chat_id, f"🔒 Actions irréversibles : <b>{'AUTORISÉES' if state['allow'] else 'refusées'}</b>")
                elif text.startswith("/brand"):
                    nom = text[len("/brand"):].strip()
                    if nom:
                        state["brand"] = nom
                        send(chat_id, f"🏷️ Marque : <b>{nom}</b>")
                    else:
                        send(chat_id, f"🏷️ Marque actuelle : <b>{state['brand']}</b>")
                elif text.startswith("/stop"):
                    if ADMIN_IDS and user_id not in ADMIN_IDS:
                        send(chat_id, "⛔ Réservé à l'admin.")
                    else:
                        send(chat_id, "👋 Arrêt du bot.")
                        print("Arrêt demandé via /stop.")
                        return
                else:
                    send(chat_id, "Commande inconnue. Tape /start pour l'aide.")

        except KeyboardInterrupt:
            print("\nArrêt.")
            return
        except requests.exceptions.RequestException as e:
            print("⚠️ Erreur réseau (retry dans 5s):", e)
            time.sleep(5)
        except Exception as e:
            print("⚠️ Erreur inattendue:", type(e).__name__, e)
            time.sleep(2)


if __name__ == "__main__":
    main()
