# -*- coding: utf-8 -*-
"""
WIRILI APP — UI Streamlit pour l'agent publicitaire Wirili.

  • Saisir un brief de campagne
  • Choisir une marque (presets) + couleurs + ton de voix
  • Choisir les formats (auto si omis)
  • Lancer la production → voir les fichiers générés + télécharger

Lancement direct : streamlit run wirili_app.py
"""
from __future__ import annotations

import sys
import shutil
import zipfile
import io
from pathlib import Path

import streamlit as st

# Importer l'agent (même dossier).
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:
    import agent_pub as W  # type: ignore
except Exception as e:
    st.error(f"Impossible de charger agent_pub.py : {e}")
    st.stop()


# --------------------------------------------------------------------------- #
#  Configuration de page
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="Wirili — Agent publicitaire",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS minimal pour un look propre.
st.markdown("""
<style>
    .block-container {padding-top: 1.5rem; max-width: 1100px;}
    h1, h2, h3 {color: #6B21A8;}
    .stButton > button {border-radius: 8px; font-weight: 600;}
    .big-title {
        background: linear-gradient(90deg, #7C3AED, #DB2777);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        font-size: 2.4rem; font-weight: 800; margin-bottom: 0.2rem;
    }
    .subtitle {color: #6B7280; font-size: 1.05rem; margin-bottom: 1.2rem;}
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
#  Presets de marques
# --------------------------------------------------------------------------- #
BRAND_PRESETS = {
    "Lumina Glow (skincare)": {
        "name": "Lumina Glow", "primary": "#0F2A2A", "accent": "#F5A65B",
        "secondary": "#E8C39E", "bg": "#FAF6F0", "text": "#1A1A1A",
        "tone": ("Bienveillant, sensoriel et confiant. Vocabulaire premium mais "
                 "accessible. Tutoiement. Met en avant l'efficacité prouvée et le "
                 "plaisir d'usage."),
        "language": "français", "hashtags": "skincare, beaute, lumina",
    },
    "FitPulse (fitness)": {
        "name": "FitPulse", "primary": "#0A0A0A", "accent": "#22D3EE",
        "secondary": "#1F2937", "bg": "#FFFFFF", "text": "#111827",
        "tone": ("Énergique, direct, motivant. Tutoiement. Langage sportif et "
                 "competitif. Appel a l'action fort."),
        "language": "français", "hashtags": "fitness, training, fitpulse",
    },
    "Maison Verte (bio)": {
        "name": "Maison Verte", "primary": "#1B5E20", "accent": "#F9A825",
        "secondary": "#A5D6A7", "bg": "#F1F8E9", "text": "#1B1B1B",
        "tone": ("Authentique, chaleureux, ecologique. Vouvoiement respectueux. "
                 "Valeurs : nature, savoir-faire, durabilite."),
        "language": "français", "hashtags": "bio, nature, maisonverte",
    },
    "Personnalisée": None,  # vide → l'utilisateur saisit tout
}

ALL_FORMATS = list(W.FORMATS.keys())


# --------------------------------------------------------------------------- #
#  Sidebar — réglages de marque
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("### 🎨 Wirili — Configuration")
    preset_name = st.selectbox("Marque (preset)", list(BRAND_PRESETS.keys()),
                               index=0)
    preset = BRAND_PRESETS[preset_name]

    if preset:
        brand_name = st.text_input("Nom de marque", preset["name"])
        primary = st.text_input("Couleur principale (hex)", preset["primary"])
        accent = st.text_input("Couleur accent / CTA (hex)", preset["accent"])
        tone = st.text_area("Ton de voix", preset["tone"], height=90)
        language = st.selectbox("Langue", ["français", "anglais", "espagnol"],
                                index=0)
        hashtags = st.text_input("Hashtags de base (virgules)",
                                 preset["hashtags"])
    else:
        brand_name = st.text_input("Nom de marque", "Ma Marque")
        primary = st.color_picker("Couleur principale", "#6B21A8")
        accent = st.color_picker("Couleur accent", "#F59E0B")
        tone = st.text_area("Ton de voix", "Professionnel et engageant.",
                            height=90)
        language = st.selectbox("Langue", ["français", "anglais", "espagnol"],
                                index=0)
        hashtags = st.text_input("Hashtags de base (virgules)", "marque, pub")

    video_provider = st.selectbox(
        "Provider vidéo",
        ["moviepy", "pollinations", "fal", "hf"],
        index=0,
        help="moviepy = gratuit sans clé (recommandé). Les autres nécessitent "
             "des clés API.",
    )

    st.markdown("---")
    st.caption("Wirili v2 — agent publicitaire autonome.\n"
               "Moteur : FreeLLMAPI / Pollinations / Pillow / moviepy.")


# --------------------------------------------------------------------------- #
#  Header
# --------------------------------------------------------------------------- #
st.markdown('<div class="big-title">🎨 Wirili</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Agent publicitaire autonome — '
            'un brief, toute une campagne.</div>', unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
#  Brief + formats
# --------------------------------------------------------------------------- #
col1, col2 = st.columns([3, 2])

with col1:
    brief = st.text_area(
        "📝 Brief de campagne",
        value=("Lancement de notre nouveau sérum éclat anti-tache. "
               "Cible : femmes 30-45 ans, urbaines, soucieuses de leur peau. "
               "Message : une peau lumineuse en 14 jours, formule naturelle."),
        height=130,
        help="Décris le produit, la cible, le message. Plus c'est précis, "
             "mieux le routeur choisit les formats.",
    )

with col2:
    use_auto = st.checkbox("Routage automatique", value=True,
                           help="Wirili choisit les formats selon les mots-clés "
                                "du brief.")
    if use_auto:
        selected = []
    else:
        selected = st.multiselect(
            "Formats à produire",
            ALL_FORMATS,
            default=["instagram", "linkedin", "video"],
        )


# --------------------------------------------------------------------------- #
#  Dossier de sortie
# --------------------------------------------------------------------------- #
workdir = HERE / "wirili_output"
workdir.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
#  Lancement
# --------------------------------------------------------------------------- #
col_run, col_info = st.columns([1, 2])
with col_run:
    run_btn = st.button("🚀 Lancer la campagne", type="primary",
                        use_container_width=True)
with col_info:
    if selected:
        st.caption(f"Formats : {', '.join(selected)}")
    else:
        st.caption("Formats : routage auto ( Wirili choisit selon le brief )")


# --------------------------------------------------------------------------- #
#  Exécution
# --------------------------------------------------------------------------- #
if run_btn:
    if not brief.strip():
        st.warning("Le brief est vide.")
        st.stop()

    # Construire l'objet Brand.
    brand = W.Brand(name=brand_name)
    brand.primary = primary
    brand.accent = accent
    if preset:
        brand.secondary = preset["secondary"]
        brand.bg = preset["bg"]
        brand.text = preset["text"]
    brand.tone = tone
    brand.language = language
    brand.hashtags_base = [h.strip().lstrip("#") for h in hashtags.split(",")
                           if h.strip()]
    brand.overlay_enabled = True

    # Lancer dans un spinner.
    with st.spinner("Wirili travaille… (copy → validation → rendu → export)"):
        try:
            agent = W.Wirili(brand, workdir,
                             video_provider=video_provider)
            manifest_path = agent.run(brief, selected or None)
        except Exception as e:
            st.error(f"❌ Erreur pendant la production : {e}")
            import traceback
            st.code(traceback.format_exc())
            st.stop()

    st.success("✅ Campagne produite !")

    # Lire le manifest.
    try:
        import json
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        manifest = {"results": []}

    # Lister les fichiers générés.
    st.markdown("### 📦 Fichiers générés")
    files = sorted(workdir.rglob("*"))
    files = [f for f in files if f.is_file()
             and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".mp4",
                                      ".pptx", ".txt", ".json", ".md")]

    if not files:
        st.info("Aucun fichier de sortie trouvé.")
    else:
        # Grille de téléchargement + aperçu.
        cols = st.columns(3)
        for i, f in enumerate(files):
            with cols[i % 3]:
                rel = f.relative_to(workdir)
                st.markdown(f"**{rel.name}**")
                st.caption(f"{f.stat().st_size // 1024} Ko")
                ext = f.suffix.lower()
                if ext in (".png", ".jpg", ".jpeg"):
                    st.image(str(f), use_container_width=True)
                elif ext == ".mp4":
                    st.video(str(f))
                else:
                    st.caption(f"Fichier : {rel}")
                with open(f, "rb") as fh:
                    st.download_button(
                        label=f"⬇️ {f.name}",
                        data=fh.read(),
                        file_name=f.name,
                        mime="application/octet-stream",
                        key=f"dl_{i}",
                    )

        # Zip global.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.write(f, f.relative_to(workdir))
        st.download_button(
            label="⬇️ Tout télécharger (ZIP)",
            data=buf.getvalue(),
            file_name="wirili_campagne.zip",
            mime="application/zip",
            use_container_width=True,
        )

    # Manifest détaillé.
    with st.expander("📋 Détails de production (manifest)"):
        st.json(manifest)
