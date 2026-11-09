# -*- coding: utf-8 -*-
"""
BOSS APP - interface Streamlit + agent publicité (Wirili) branché sur le Boss

Tourne en LOCAL sous FreeLLMAPI (http://127.0.0.1:31415). Aucune clé Anthropic.

Fichiers à placer dans le même dossier :
  boss_agent.py   boss_app.py   agent_pub.py

Installation : pip install streamlit pillow python-pptx
              (anthropic N'EST PLUS nécessaire)
Lancement    : streamlit run boss_app.py
Sur téléphone: streamlit run boss_app.py --server.address 0.0.0.0
               puis ouvrir http://<IP-de-l'ordinateur>:8501 (même Wi-Fi)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Forcer UTF-8 avant l'import de Streamlit (Windows cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import streamlit as st

from agent_pub import FORMATS, Brand, Wirili
from boss_agent import Boss, CallableWorker, Deliverable, Scope

AD_ROLE = "agent_publicite_posts_slides_fiches"


# -------------------------------------------------------------------------- #
#  Branchement de l'agent publicité (Wirili)
# -------------------------------------------------------------------------- #
def _parse_formats(instructions: str):
    """Extrait les formats demandés depuis les instructions (ex: 'posts linkedin
    instagram, slides et une fiche'). Retourne None => auto-routage Wirili."""
    b = instructions.lower()
    found = []
    for f in FORMATS:
        if f in b or f.replace("_", " ") in b:
            found.append(f)
    # synonymes courants
    if "post" in b and "linkedin" not in found:
        found.append("linkedin")
    if "post" in b and "instagram" not in found and "insta" in b:
        found.append("instagram")
    return list(dict.fromkeys(found)) or None


def build_boss(allow_irreversible: bool, brand_name: str,
               video_provider: str = "moviepy") -> Boss:
    """Construit le Boss avec l'agent publicité Wirili enregistré."""
    # Dans Streamlit, input() est impossible : l'approbation est une case à cocher.
    boss = Boss(approver=lambda actor, scope, detail: allow_irreversible)

    def run_ad(task) -> Deliverable:
        brand = Brand(name=brand_name)
        formats = _parse_formats(task.instructions)
        agent = Wirili(brand, workdir=boss.run_dir, video_provider=video_provider)
        manifest_path = agent.run(task.instructions, requested=formats)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        results = manifest.get("formats", [])
        if not results:
            raise ValueError("l'agent publicité n'a produit aucun livrable")
        # Le dossier de sortie de Wirili contient assets/, text/, manifest.json
        folder = manifest_path.parent
        return Deliverable(kind="file",
                           content=json.dumps(manifest, ensure_ascii=False),
                           path=str(folder))

    boss.register(CallableWorker(AD_ROLE, run_ad), {Scope.READ, Scope.WRITE})
    return boss


# -------------------------------------------------------------------------- #
#  Docteur (vérification santé)
# -------------------------------------------------------------------------- #
def _run_doctor():
    """Vérifie disque + LLM et affiche le résultat dans la sidebar."""
    import tempfile
    from boss_agent import Doctor, LLM, Audit, Permissions
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    audit = Audit(tmp / "audit.jsonl")
    perms = Permissions(audit, lambda *a, **k: False)
    doctor = Doctor(audit, perms, tmp)
    llm = LLM()
    with st.spinner("Vérification..."):
        sante = doctor.health_check(llm)
    st.session_state["sante"] = sante


sante = st.session_state.get("sante")
if sante:
    st.subheader("🩺 Santé du Boss")
    # Disque
    if sante.get("disque"):
        st.success("💾 Disque : OK")
    else:
        st.error("💾 Disque : ECHEC")
    # LLM
    if sante.get("llm"):
        st.success(f"🧠 LLM : OK — mode {sante.get('llm_mode', '?')}")
    else:
        st.error("🧠 LLM : ECHEC — FreeLLMAPI injoignable")
        st.markdown("""
        **FreeLLMAPI ne répond pas sur `http://127.0.0.1:31415`.**

        Pour le démarrer :
        1. Ouvre l'app **FreeLLMAPI** (menu Démarrer ou double-clic sur `FreeLLMAPI.exe`)
        2. Attends que son serveur local démarre (icône dans la barre des tâches)
        3. Re-clique sur **🩺 Docteur**

        Si FreeLLMAPI refuse de fonctionner, tu peux :
        - Installer une clé `FREELLMAPI_KEY` alternative
        - Ou utiliser un autre provider (Pollinations, Fal.ai…)
        """)
    # Providers (fallbacks)
    providers = sante.get("providers", [])
    if providers:
        with st.expander(f"Providers configurés ({len(providers)})"):
            st.json(providers)


# -------------------------------------------------------------------------- #
#  Interface
# -------------------------------------------------------------------------- #
st.set_page_config(page_title="Boss Agent", page_icon="🧠", layout="centered")
st.title("🧠 Boss Agent")
st.caption("Planifie, délègue, contrôle, répare et livre. "
           "Moteur LLM : FreeLLMAPI local (127.0.0.1:31415).")

with st.sidebar:
    st.header("Réglages")
    brand = st.text_input("Marque (agent publicité)", "Lumina Glow")
    video_provider = st.selectbox(
        "Provider vidéo (agent pub)",
        options=["moviepy", "pollinations", "fal", "hf"],
        index=0,
        help="moviepy = gratuit sans clé (image animée). Les autres nécessitent "
             "une clé d'API (FAL_KEY, HF_TOKEN, POLLINATIONS_API_KEY).",
    )
    allow = st.checkbox("Autoriser les actions irréversibles "
                        "(supprimer, envoyer, dépenser)", value=False)
    st.caption("Décoché : le Boss refuse ces actions, tout le reste est autorisé.")
    st.divider()
    st.caption("LLM : FreeLLMAPI local — gratuit, sans clé externe.")
    st.divider()
    if st.button("🩺 Docteur — vérifier la santé", use_container_width=True):
        _run_doctor()

mission = st.text_area(
    "Mission", height=160,
    placeholder="Ex. : Prépare le lancement de la crème visage : "
                "posts LinkedIn et Instagram, slides, et un script "
                "qui calcule le prix de revient.",
)

if st.button("🚀 Lancer le Boss", type="primary", disabled=not mission.strip()):
    boss = build_boss(allow, brand, video_provider)
    with st.spinner("Le Boss travaille... (FreeLLMAPI local)"):
        report = boss.run(mission)
    st.session_state["report"] = report
    st.session_state["run_dir"] = str(boss.run_dir)

report = st.session_state.get("report")
if report:
    if "erreur" in report:
        st.error(f"{report['erreur']}")
        if report.get("sante"):
            st.json(report["sante"])
        st.stop()

    (st.success if report["statut"] == "complet" else st.warning)(
        f"Statut : {report['statut']}")

    run_dir = st.session_state.get("run_dir")
    if run_dir:
        st.caption(f"Dossier de run : `{run_dir}`")

    st.subheader("Tâches")
    st.table([{"id": k, "tâche": v["titre"], "agent": v["role"],
               "statut": v["statut"], "essais": v["essais"]}
              for k, v in report["taches"].items()])

    if report["a_traiter_par_humain"]:
        st.error("⚠️ À traiter par un humain : " + ", ".join(report["a_traiter_par_humain"]))

    if report["incidents"]:
        with st.expander(f"🩺 Interventions du docteur ({len(report['incidents'])})"):
            st.json(report["incidents"])

    st.subheader("Livrables")
    for item in report["livrables"]:
        p = Path(item)
        files = sorted(p.iterdir()) if p.is_dir() else [p]
        for f in files:
            if f.is_dir():
                continue
            if f.suffix.lower() == ".png":
                st.image(str(f), caption=f.name)
            if f.is_file():
                st.download_button(f"⬇️ {f.name}", f.read_bytes(),
                                   file_name=f.name, key=str(f))
