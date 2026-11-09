# Boss Agent

[![CI](https://github.com/haouchinelotfi-ui/boss-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/haouchinelotfi-ui/boss-agent/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Local LLM](https://img.shields.io/badge/LLM-FreeLLMAPI%20local-green.svg)](http://127.0.0.1:31415)

Manager autonome qui **planifie, délègue, contrôle, répare et livre**.
Tourne 100 % en local via [FreeLLMAPI](http://127.0.0.1:31415) — aucun token
cloud payant requis.

```
Mission (texte libre)
   ↓
   ┌──────────────────────────── BOSS ────────────────────────────┐
   │ 1. Planner      -> découpe en tâches + dépendances (DAG)     │
   │ 2. Dispatcher   -> assigne chaque tâche au bon agent         │
   │ 3. Exécution    -> en parallèle quand indépendantes          │
   │ 4. Contrôle     -> validation technique + revue qualité      │
   │ 5. DOCTEUR      -> retry / renvoi / smoke test / coupe-circuit│
   │ 6. Rapport      -> livrables + incidents + audit             │
   └──────────────────────────────────────────────────────────────┘
        ↓ délègue à
   Agents : rédacteur, développeur, analyste, designer,
            généraliste, et l'agent publicitaire Wirili.
```

## Fichiers

| Fichier | Rôle |
|---|---|
| `boss_agent.py` | Le Boss : planification, orchestration parallèle, docteur (réparation), rapport. LLM via FreeLLMAPI local. |
| `boss_app.py` | Interface Streamlit + branchement de l'agent publicité (Wirili). |
| `agent_pub.py` | Agent publicitaire autonome (Wirili) : posts, slides, fiches, vidéo. Texte=FreeLLMAPI, image=Pollinations, vidéo=multi-provider. |
| `boss_telegram.py` | Bot Telegram — pilote le Boss depuis ton téléphone, n'importe où (Internet, pas de Wi-Fi partagé). |
| `install_boss_shortcut.py` | Crée l'icône + raccourci Bureau (Windows). |
| `.github/workflows/ci.yml` | CI GitHub Actions : lint (ruff) + vérif de syntaxe + import du cœur à chaque push. |

## Installation

```bash
pip install streamlit pillow python-pptx
pip install moviepy        # optionnel : fallback vidéo gratuit (image animée)
```

FreeLLMAPI doit tourner sur `http://127.0.0.1:31415` (application Electron locale,
~280 modèles gratuits routés via `model=auto`).

## Lancement

```bash
# CLI
python boss_agent.py "Prépare le dossier de lancement de la crème visage."

# Interface web (Streamlit)
streamlit run boss_app.py

# Depuis le téléphone (même Wi-Fi)
streamlit run boss_app.py --server.address 0.0.0.0
# puis http://<IP-du-PC>:8501
```

### Pilotage Telegram (depuis n'importe où)

L'avantage de Telegram vs Streamlit : il passe par Internet, donc tu pilotes
le Boss depuis ton téléphone **sans être sur le même Wi-Fi que le PC**.

1. Crée un bot via [@BotFather](https://t.me/BotFather) sur Telegram → récupère le token.
2. (Optionnel) Récupère ton ID utilisateur via [@userinfobot](https://t.me/userinfobot) pour être admin du `/stop`.
3. Lance :

```bash
pip install requests
export BOSS_TELEGRAM_TOKEN=123456:ABC-...   # Windows : set BOSS_TELEGRAM_TOKEN=...
export BOSS_ADMIN_IDS=123456789              # ton ID Telegram (admin)
python boss_telegram.py
```

Commandes Telegram : `/mission <texte>`, `/sante`, `/run`, `/allow`, `/brand <nom>`, `/stop`.

Ou, sous Windows, après `python install_boss_shortcut.py` : double-cliquer
sur **Boss Agent** sur le Bureau.

## CI (GitHub Actions)

À chaque `push` sur `main`, le workflow `.github/workflows/ci.yml` :
- **lint** avec `ruff` (erreurs de syntaxe + undefined names),
- **compile** tous les `.py` (`py_compile`),
- **importe** le cœur `boss_agent.py` pour vérifier qu'il charge sans erreur.

Le badge de statut apparaîtra dans l'onglet Actions du dépôt.

### Tests unitaires (44 tests, sans réseau)

```bash
pip install pytest requests
python -m pytest test_boss.py -v
```

Couvrent : `_parse_json`, `strip_fences`, `validate` (text/python/json/file),
`Permissions` (scopes + actions irréversibles), `Doctor` (diagnose, smoke test,
coupe-circuit), `Boss.plan` (routage de rôle), `Boss.run` (orchestration complète
avec LLM mocké, escalade, dépendances bloquées), `CallableWorker`.

Les tests utilisent un `FakeLLM` qui ne touche jamais le réseau — ils tournent
en ~1,5 s et sont exécutés automatiquement par la CI à chaque push.

## Sécurité

Le Boss détient tous les droits (lecture, écriture, exécution, réseau,
suppression, envoi externe, dépenses). Les actions **irréversibles**
(supprimer, envoyer à l'extérieur, dépenser) exigent une approbation
humaine. Désactivable : `Boss(approver=lambda *a: True)`.

Tout est tracé dans `runs/<date>/audit.jsonl`.

## Brancher ses propres agents

```python
from boss_agent import Boss, CallableWorker, Deliverable, Scope

boss = Boss(approver=lambda *a: True)

def mon_agent(task) -> Deliverable:
    # ... ta logique ...
    return Deliverable(kind="file", content="...", path="/chemin/vers/dossier")

boss.register(CallableWorker("mon_role", mon_agent), {Scope.READ, Scope.WRITE})
print(boss.run("ta mission"))
```

## Livrables

Chaque exécution produit `runs/<horodatage>/` :
- `rapport.json` — statut, tâches, incidents, fichiers livrés
- `state.json` — checkpoint de l'état des tâches
- `audit.jsonl` — journal d'audit complet
- les livrables (`t1_developpeur.py`, `t2_redacteur.md`, dossier `output/...` pour la pub…)

## Licence

MIT
