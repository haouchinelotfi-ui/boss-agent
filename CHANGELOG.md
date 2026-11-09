# Changelog

Toutes les versions notables de Boss Agent sont documentées ici.
Le format s'inspire de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).

## [1.0.0] — 2025

### Première version publique

#### Ajouté
- **Boss agent** (`boss_agent.py`) : manager autonome qui planifie, délègue,
  contrôle, répare et livre.
  - Planification : découpe la mission en tâches liées (DAG) avec rôle,
    consignes et critères d'acceptation.
  - Distribution : chaque tâche va à l'agent adapté ; parallélisme des tâches
    indépendantes (`ThreadPoolExecutor`, 4 workers).
  - Contrôle : validation technique (JSON valide, code qui compile) puis
    revue qualité face aux critères.
  - **Docteur** (maintenance et réparation) :
    - panne réseau / limite d'API : retry avec backoff progressif ;
    - livrable non conforme : renvoyé à l'agent avec la liste précise des défauts ;
    - code qui plante : smoke test isolé puis correction avec l'erreur exacte ;
    - agent qui échoue 3 fois : coupe-circuit et passage au généraliste ;
    - échec persistant : tâche signalée dans `a_traiter_par_humain`.
  - Rapport : tout est enregistré dans `runs/<date>/` (livrables, `state.json`,
    `rapport.json`, `audit.jsonl`).
- **Interface Streamlit** (`boss_app.py`) : saisie de la mission, tableau des
  tâches, interventions du docteur, livrables (images affichées, fichiers à
  télécharger).
- **Agent publicité Wirili** (`agent_pub.py`) : posts LinkedIn/Instagram,
  slides PowerPoint, fiches, vidéo. Texte=FreeLLMAPI, image=Pollinations,
  vidéo=multi-provider. Branché dans le Boss sous le rôle
  `agent_publicite_posts_slides_fiches`.
- **Bot Telegram** (`boss_telegram.py`) : pilote le Boss depuis un téléphone
  n'importe où (Internet, pas de Wi-Fi partagé). Commandes `/mission`, `/sante`,
  `/run`, `/allow`, `/brand`, `/stop`. Envoi des livrables en pièces jointes.
- **Raccourci Bureau Windows** (`install_boss_shortcut.py` + `boss.ico`).
- **CI GitHub Actions** (`.github/workflows/ci.yml`) : lint `ruff` + compilation
  + import du cœur à chaque push.
- **Sécurité** : le Boss a tous les droits, mais les actions irréversibles
  (supprimer, envoyer à l'extérieur, dépenser) demandent approbation.
  Désactivable via `approver=lambda *a: True`.

#### Moteur LLM
- 100 % local via [FreeLLMAPI](http://127.0.0.1:31415) — aucun token cloud
  payant requis.

## Lien de comparaison

[1.0.0]: https://github.com/haouchinelotfi-ui/boss-agent/releases/tag/v1.0.0
