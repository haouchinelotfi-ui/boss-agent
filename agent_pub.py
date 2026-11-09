#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wirili — Agent publicitaire autonome v2.

Pipeline en 5 étapes :
  1. Router        : choisit les formats (linkedin, facebook, instagram, fiche_pub,
                     maquette, slides, video).
  2. CopyAgent     : rédige accroche / corps / CTA / hashtags + idee_visuelle
                     (prompt image EN) pour chaque format.
  3. Validator     : contrôle limites. Renvoie au CopyAgent (max 2 fois).
  4. Renderers     : image = Pollinations.ai (GRATUIT, sans clé) + fallback Pillow ;
                     vidéo = génération IA multi-provider (Pollinations / Fal / HuggingFace)
                     + fallback MoviePy (image fixe animée).
  5. Exporter      : output/<marque>/ + manifest.json.

Fonctionne GRATUIT hors-ligne (stub + Pillow + MoviePy) et EN LIGNE avec :
  - Texte  : FreeLLMAPI local (127.0.0.1:31415, model=auto) — GRATUIT, sans clé
             → ou Anthropic si ANTHROPIC_API_KEY présente.
  - Image  : Pollinations.ai — GRATUIT, sans clé.
  - Vidéo  : au choix via --video-provider : pollinations | fal | hf | moviepy.

Installation :
    pip install requests pillow python-pptx
    pip install moviepy        # pour le fallback vidéo (image fixe -> mp4)
    pip install anthropic      # optionnel : copy par Claude (sinon FreeLLMAPI/stub)

Lancement :
    python agent_pub.py "Lancement crème visage" --brand "Lumina Glow" \\
        --formats linkedin instagram video slides --video-provider fal
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Forcer la console en UTF-8 (Windows cp1252 ne gère pas ✓ ⚠ …).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# ---------------------------------------------------------------------------
# Dépendances tierces — importées tardivement / optionnellement.
# ---------------------------------------------------------------------------
try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore
except ImportError:  # pragma: no cover
    Image = None  # type: ignore

try:
    import requests  # type: ignore
except ImportError:  # pragma: no cover
    requests = None  # type: ignore


# ===========================================================================
#  CONFIGURATION
# ===========================================================================
@dataclass
class Brand:
    """Identité de marque. Tout est ajustable ici ou via CLI."""
    name: str = "Lumina Glow"
    primary: str = "#0F2A2A"     # vert profond
    accent: str = "#F5A65B"      # orange chaud
    secondary: str = "#E8C39E"   # sable doré
    bg: str = "#FAF6F0"          # crème
    text: str = "#1A1A1A"
    tone: str = (
        "Bienveillant, sensoriel et confiant. Vocabulaire premium mais accessible. "
        "Tutoiement. Met en avant l'efficacité prouvée et le plaisir d'usage."
    )
    language: str = "français"
    font_name: str = "DejaVuSans"
    hashtags_base: List[str] = field(default_factory=lambda: ["skincare", "beaute", "lumina"])
    # Logo optionnel (PNG transparent) : s'il existe, il est overlay sur les
    # images IA (Pollinations) et le fallback Pillow, pour la cohérence de marque.
    logo_path: Optional[str] = None
    overlay_enabled: bool = True  # mettre False pour garder l'image IA brute

    def to_prompt_context(self) -> str:
        return (
            f"Marque : {self.name}. Ton : {self.tone}. Langue : {self.language}. "
            f"Hashtags récurrents : {', '.join('#' + h for h in self.hashtags_base)}."
        )


FORMATS: Dict[str, Dict[str, Any]] = {
    "linkedin":  {"size": (1200, 627),  "max_chars": 3000, "max_hashtags": 5,  "render": "image"},
    "facebook":  {"size": (1200, 630),  "max_chars": 2000, "max_hashtags": 3,  "render": "image"},
    "instagram": {"size": (1080, 1080), "max_chars": 2200, "max_hashtags": 30, "render": "image"},
    "fiche_pub": {"size": (1240, 1754), "max_chars": 900,  "max_hashtags": 0,  "render": "image"},
    "maquette":  {"size": (1080, 1920), "max_chars": 300,  "max_hashtags": 0,  "render": "image"},
    "slides":    {"size": (1920, 1080), "max_chars": 400,  "max_hashtags": 0,
                  "render": "slides", "max_slides": 8, "min_slides": 4},
    "video":     {"size": (1080, 1920), "max_chars": 300,  "max_hashtags": 5,
                  "render": "video", "max_duration": 5},
}


# ===========================================================================
#  1. ROUTER
# ===========================================================================
class Router:
    def __init__(self, formats_cfg: Dict[str, Dict[str, Any]]):
        self.cfg = formats_cfg

    def select(self, requested: Optional[List[str]], brief: str) -> List[str]:
        if requested:
            bad = [f for f in requested if f not in self.cfg]
            if bad:
                raise ValueError(f"Formats inconnus : {bad}. Disponibles : {list(self.cfg)}")
            return list(requested)
        # Auto-routage par mots-clés
        b = brief.lower()
        auto: List[str] = []
        if any(k in b for k in ("lancement", "produit", "innovation", "b2b")):
            auto.append("linkedin")
        if any(k in b for k in ("lancement", "promo", "offre")):
            auto.append("facebook")
        if any(k in b for k in ("lancement", "beauté", "mode", "visuel")):
            auto.append("instagram")
        if any(k in b for k in ("présentation", "pitch", "deck", "investisseur")):
            auto.append("slides")
        if any(k in b for k in ("reel", "tiktok", "vidéo", "video", "motion")):
            auto.append("video")
        if not auto:
            auto = ["instagram", "video", "linkedin"]
        # dédoublonne
        seen, out = set(), []
        for f in auto:
            if f not in seen:
                seen.add(f)
                out.append(f)
        return out


# ===========================================================================
#  2. COPYAGENT — couche LLM multi-provider (GRATUIT d'abord)
# ===========================================================================
class LLMProvider:
    """Abstraction sur le LLM. Priorité : FreeLLMAPI (gratuit) → Anthropic → stub."""

    def __init__(self):
        self.mode = "stub"
        self._freellm_key: Optional[str] = None
        self._freellm_base = os.environ.get("FREELLMAPI_BASE", "http://127.0.0.1:31415")
        self._anthropic_client = None

        # 1) FreeLLMAPI local (gratuit, model=auto)
        key = self._read_freellm_key()
        if key:
            self._freellm_key = key
            self.mode = "freellmapi"
            return
        # 2) Anthropic si clé présente
        akey = os.environ.get("ANTHROPIC_API_KEY")
        if akey:
            try:
                import anthropic  # type: ignore
                self._anthropic_client = anthropic.Anthropic(api_key=akey)
                self.mode = "anthropic"
                return
            except Exception:
                pass
        # 3) stub
        self.mode = "stub"

    @staticmethod
    def _read_freellm_key() -> Optional[str]:
        """Lit la clé unifiée de FreeLLMAPI dans sa DB SQLite (si installée)."""
        try:
            import sqlite3
            db = os.path.join(os.environ.get("APPDATA", ""), "FreeLLMAPI", "freeapi.db")
            if not os.path.exists(db):
                return None
            c = sqlite3.connect(db)
            cur = c.execute("SELECT value FROM settings WHERE key='unified_api_key'")
            row = cur.fetchone()
            c.close()
            return row[0] if row else None
        except Exception:
            return None

    def chat_json(self, system: str, user: str, max_tokens: int = 1500) -> Dict[str, Any]:
        if self.mode == "freellmapi":
            return self._freellm_chat(system, user, max_tokens)
        if self.mode == "anthropic":
            return self._anthropic_chat(system, user, max_tokens)
        raise RuntimeError("stub mode : chat_json non disponible")

    # ---- FreeLLMAPI (OpenAI-compatible) ----------------------------------
    def _freellm_chat(self, system: str, user: str, max_tokens: int) -> Dict[str, Any]:
        # 'auto' = routing intelligent de FreeLLMAPI (le seul vraiment fiable
        # sans clé provider additionnelle). On retente 2x en cas de JSON tronqué.
        last_err: Optional[Exception] = None
        for attempt in range(2):
            payload = {
                "model": "auto",
                "messages": [
                    {"role": "system",
                     "content": system + "\nRéponds UNIQUEMENT en JSON valide, sans markdown ni texte autour."},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.7,
            }
            try:
                data = self._http_json("POST", f"{self._freellm_base}/v1/chat/completions",
                                       payload, auth=self._freellm_key)
                content = data["choices"][0]["message"]["content"]
                return LLMProvider._parse_json(content)
            except Exception as e:
                last_err = e
                # si le JSON est tronqué, on augmente max_tokens et on retente
                if attempt == 0 and max_tokens < 4000:
                    max_tokens = min(max_tokens * 2, 4000)
                    continue
                break
        raise RuntimeError(f"FreeLLMAPI : échec ({last_err})")

    # ---- Anthropic --------------------------------------------------------
    def _anthropic_chat(self, system: str, user: str, max_tokens: int) -> Dict[str, Any]:
        r = self._anthropic_client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
            max_tokens=max_tokens,
            system=system + "\nRéponds UNIQUEMENT en JSON valide, sans markdown.",
            messages=[{"role": "user", "content": user}],
        )
        raw = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return LLMProvider._parse_json(raw)

    # ---- Utilitaires HTTP -------------------------------------------------
    @staticmethod
    def _http_json(method: str, url: str, payload: Dict[str, Any],
                   auth: Optional[str] = None, timeout: int = 120) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {auth}"
        body = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    @staticmethod
    def _parse_json(raw: str) -> Dict[str, Any]:
        raw = raw.strip().strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
        s = raw.find("{")
        e = raw.rfind("}")
        if s != -1 and e != -1 and e > s:
            raw = raw[s:e + 1]
        return json.loads(raw)


class CopyAgent:
    """Rédige le copy + le prompt visuel (idee_visuelle) pour un format."""

    def __init__(self, llm: LLMProvider, brand: Brand):
        self.llm = llm
        self.brand = brand

    def write(self, fmt: str, brief: str, errors: Optional[List[str]] = None) -> Dict[str, Any]:
        if self.llm.mode != "stub":
            try:
                return self._llm_write(fmt, brief, errors)
            except Exception as e:
                print(f"  ⚠️  LLM ({self.llm.mode}) en échec ({e}) — fallback stub.",
                      file=sys.stderr)
        return self._stub(fmt, brief)

    def _llm_write(self, fmt: str, brief: str, errors: Optional[List[str]]) -> Dict[str, Any]:
        spec = FORMATS[fmt]
        if fmt == "slides":
            schema = '{"accroche":"","idee_visuelle":"EN prompt","slides":[{"titre":"","points":["",""]}]}'
        else:
            schema = ('{"accroche":"","corps":"","cta":"","hashtags":[""],'
                      '"idee_visuelle":"very precise English prompt for AI commercial image"}')
        system = (
            f"Tu es Wirili, copywriter publicitaire senior. {self.brand.to_prompt_context()}. "
            f"Format : {fmt}. Limites : {spec}. Accroche forte, bénéfice client clair, un seul CTA. "
            f"Remplis 'idee_visuelle' : prompt descriptif en anglais, style photo publicitaire pro, "
            f"pour générer une image {spec['size'][0]}x{spec['size'][1]}."
        )
        user = f"Brief : {brief}\nFormat cible : {fmt}\nSchéma JSON attendu : {schema}"
        if errors:
            user += "\nCorrige ces erreurs de la version précédente :\n- " + "\n- ".join(errors)
        return self.llm.chat_json(system, user)

    def _stub(self, fmt: str, brief: str) -> Dict[str, Any]:
        spec = FORMATS[fmt]
        accroche = f"{self.brand.name} — {brief[:60]}"
        corps = (f"{brief}\n\nUne formule pensée pour révéler l'éclat naturel de votre peau, "
                 "jour après jour. Texture fondante, parfum délicat, résultats visibles.")
        cta = "Découvrez la collection dès aujourd'hui."
        hashtags = list(self.brand.hashtags_base[: spec["max_hashtags"]])
        idee = (f"luxurious skincare cream jar on white marble, soft golden light, "
                f"minimalist premium cosmetic ad, {self.brand.name} branding, "
                f"highly detailed commercial photography, 8k")
        if fmt == "slides":
            slides = [
                {"titre": self.brand.name, "points": [brief, "Une nouvelle ère skincare", self.brand.tone[:40]]},
                {"titre": "Le besoin", "points": ["Peau terne", "Manque d'éclat", "Stress quotidien"]},
                {"titre": "La solution", "points": ["Formule éclaircissante", "Actifs naturels", "Testé cliniquement"]},
                {"titre": "Résultats", "points": ["+34% d'éclat", "96% satisfaction", "Dès 2 semaines"]},
                {"titre": "Disponibilité", "points": ["En ligne", "Points de vente", "Lancement J-0"]},
            ]
            return {"accroche": accroche, "idee_visuelle": idee, "slides": slides}
        return {"accroche": accroche, "corps": corps, "cta": cta,
                "hashtags": hashtags, "idee_visuelle": idee}


# ===========================================================================
#  3. VALIDATOR
# ===========================================================================
class Validator:
    MAX_RETRIES = 2

    def validate(self, fmt: str, content: Dict[str, Any]) -> List[str]:
        spec = FORMATS[fmt]
        errs: List[str] = []
        if fmt == "slides":
            slides = content.get("slides", [])
            if not slides:
                errs.append("aucune slide")
            elif len(slides) > spec["max_slides"]:
                errs.append(f"{len(slides)} slides > max {spec['max_slides']}")
            return errs
        total = (len(content.get("accroche", "")) + len(content.get("corps", ""))
                 + len(content.get("cta", "")))
        if total > spec["max_chars"]:
            errs.append(f"{total} caractères > max {spec['max_chars']}")
        if len(content.get("hashtags", [])) > spec["max_hashtags"]:
            errs.append(f"trop de hashtags (max {spec['max_hashtags']})")
        if not content.get("accroche"):
            errs.append("accroche manquante")
        if not content.get("idee_visuelle"):
            errs.append("idee_visuelle manquante (prompt image requis)")
        return errs


# ===========================================================================
#  4a. RENDU IMAGE — Pollinations (GRATUIT sans clé) + fallback Pillow
# ===========================================================================
class ImageRenderer:
    """Image = Pollinations.ai (gratuit) ; fallback Pillow si échec."""

    POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}?width={w}&height={h}&nologo=true&seed={seed}"

    def __init__(self, brand: Brand):
        self.brand = brand
        self._font_cache: Dict[tuple, Any] = {}

    def render(self, fmt: str, content: Dict[str, Any], path: Path) -> Path:
        w, h = FORMATS[fmt]["size"]
        prompt = content.get("idee_visuelle") or f"Commercial product background for {self.brand.name}"
        # Seed variable par prompt : évite des images identiques entre campagnes
        # au format identique, tout en restant reproductible pour un même brief.
        seed = abs(hash((prompt, fmt))) % 1000000
        if self._pollinations(prompt, w, h, path, seed=seed):
            if self.brand.overlay_enabled:
                self._overlay_brand(path, fmt, content)
            return path
        return self._pillow_fallback(fmt, content, path)

    # ---- Overlay de marque sur image IA ----------------------------------
    # Pollinations renvoie une photo brute sans identité de marque. On pose un
    # bandeau discret (couleur primary semi-transparente) + nom de marque + CTA,
    # pour la cohérence d'une campagne à l'autre. Optionnel : logo PNG.
    def _overlay_brand(self, path: Path, fmt: str, content: Dict[str, Any]) -> None:
        if Image is None:
            return  # Pillow absent : on garde l'image IA brute
        w, h = FORMATS[fmt]["size"]
        try:
            img = Image.open(path).convert("RGBA")
        except Exception:
            return
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        # bandeau bas (couleur primary, opacité ~78%)
        bh = int(h * 0.12)
        d.rectangle([0, h - bh, w, h], fill=self._hex(self.brand.primary) + (199,))
        m = int(w * 0.05)
        # nom de marque
        d.text((m, h - bh + int(bh * 0.28)), self.brand.name.upper(),
               font=self._font(int(w * 0.032), bold=True),
               fill=self._hex(self.brand.secondary))
        # CTA à droite
        cta = content.get("cta", "")
        if cta:
            f_cta = self._font(int(w * 0.028), bold=True)
            bw, bhh = int(w * 0.34), int(bh * 0.45)
            bx = w - bw - m
            by = h - bh + (bh - bhh) // 2
            d.rounded_rectangle([bx, by, bx + bw, by + bhh], radius=bhh // 2,
                                fill=self._hex(self.brand.accent))
            d.text((bx + bw // 2, by + bhh // 2), cta, font=f_cta,
                   fill=self._hex(self.brand.primary), anchor="mm")
        # logo optionnel
        if self.brand.logo_path:
            try:
                logo = Image.open(self.brand.logo_path).convert("RGBA")
                lw = int(w * 0.18)
                ratio = lw / logo.width
                logo = logo.resized((lw, int(logo.height * ratio))) \
                    if hasattr(logo, "resized") else logo.resize((lw, int(logo.height * ratio)))
                overlay.alpha_composite(logo, (m, int(h * 0.04)))
            except Exception:
                pass
        out = Image.alpha_composite(img, overlay).convert("RGB")
        out.save(path)
        print("    [image] overlay marque appliqué")

    # ---- Pollinations.ai (gratuit, sans clé) ------------------------------
    # Pollinations limite le débit : on retente avec backoff (402 / 429).
    POLLINATIONS_MAX_RETRIES = 3
    POLLINATIONS_BACKOFF = 8  # secondes entre tentatives

    def _pollinations(self, prompt: str, w: int, h: int, path: Path,
                      seed: int = 42, timeout: int = 180) -> bool:
        enhanced = f"{prompt}, professional commercial photography, highly detailed, 8k"
        enc = urllib.parse.quote(enhanced)
        url = self.POLLINATIONS_URL.format(prompt=enc, w=w, h=h, seed=seed)
        last_err = ""
        for attempt in range(self.POLLINATIONS_MAX_RETRIES):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Wirili/2.0"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = r.read()
                if len(data) < 1000:
                    last_err = "réponse trop courte"
                else:
                    path.write_bytes(data)
                    print(f"    [image] Pollinations OK ({len(data) // 1024} KB)"
                          + (f" tentative {attempt + 1}" if attempt else ""))
                    return True
            except Exception as e:
                last_err = str(e)
            # backoff avant la prochaine tentative
            if attempt < self.POLLINATIONS_MAX_RETRIES - 1:
                time.sleep(self.POLLINATIONS_BACKOFF)
        print(f"    [image] Pollinations échec ({last_err}) — fallback Pillow")
        return False

    # ---- Fallback Pillow --------------------------------------------------
    def _pillow_fallback(self, fmt: str, content: Dict[str, Any], path: Path) -> Path:
        if Image is None:
            raise RuntimeError("Pillow absent (pip install pillow).")
        w, h = FORMATS[fmt]["size"]
        img = Image.new("RGB", (w, h), self._hex(self.brand.bg))
        d = ImageDraw.Draw(img)
        m = int(w * 0.08)

        # bande de marque
        d.rectangle([0, 0, w, int(h * 0.08)], fill=self._hex(self.brand.primary))
        d.text((m, int(h * 0.02)), self.brand.name.upper(),
               font=self._font(int(w * 0.035), bold=True),
               fill=self._hex(self.brand.secondary))

        y = int(h * 0.14)
        f_title = self._font(int(w * 0.072), bold=True)
        for line in self._wrap(d, content.get("accroche", ""), f_title, w - 2 * m):
            d.text((m, y), line, font=f_title, fill=self._hex(self.brand.primary))
            y += int(w * 0.09)
        y += int(h * 0.03)

        f_body = self._font(int(w * 0.033))
        body = content.get("corps", "")[:600]
        for line in self._wrap(d, body, f_body, w - 2 * m):
            d.text((m, y), line, font=f_body, fill=self._hex(self.brand.text))
            y += int(w * 0.045)

        # bouton CTA
        f_cta = self._font(int(w * 0.04), bold=True)
        bw, bh = int(w * 0.6), int(h * 0.07)
        by = h - int(h * 0.18)
        d.rounded_rectangle([m, by, m + bw, by + bh], radius=bh // 2,
                            fill=self._hex(self.brand.accent))
        d.text((m + bw // 2, by + bh // 2), content.get("cta", ""),
               font=f_cta, fill=self._hex(self.brand.primary), anchor="mm")
        # hashtags
        if content.get("hashtags"):
            tags = " ".join("#" + h for h in content["hashtags"])
            f_tag = self._font(int(w * 0.028))
            d.text((m, h - int(h * 0.07)), tags, font=f_tag,
                   fill=self._hex(self.brand.primary), anchor="ls")
        img.save(path)
        print("    [image] Pillow fallback OK")
        return path

    # ---- utils ------------------------------------------------------------
    def _font(self, size: int, bold: bool = False) -> Any:
        key = (size, bold)
        if key in self._font_cache:
            return self._font_cache[key]
        cands = ([f"{self.brand.font_name}-Bold.ttf", "DejaVuSans-Bold.ttf", "Arial-Bold.ttf"]
                 if bold else [f"{self.brand.font_name}.ttf", "DejaVuSans.ttf", "Arial.ttf"])
        font = None
        for c in cands:
            try:
                font = ImageFont.truetype(c, size)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
        self._font_cache[key] = font
        return font

    @staticmethod
    def _hex(c: str) -> tuple:
        c = c.lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))

    def _wrap(self, draw: Any, text: str, font: Any, max_w: int) -> List[str]:
        lines, line = [], ""
        for word in (text or "").split():
            test = f"{line} {word}".strip()
            if draw.textlength(test, font=font) <= max_w:
                line = test
            else:
                lines.append(line)
                line = word
        return lines + ([line] if line else [])


# ===========================================================================
#  4b. RENDU SLIDES — python-pptx
# ===========================================================================
class SlidesRenderer:
    def __init__(self, brand: Brand):
        self.brand = brand

    def render(self, content: Dict[str, Any], path: Path) -> Path:
        from pptx import Presentation  # type: ignore
        from pptx.util import Inches, Pt  # type: ignore
        from pptx.dml.color import RGBColor  # type: ignore

        def hx(c: str) -> Any:
            c = c.lstrip("#")
            return RGBColor(int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))

        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
        blank = prs.slide_layouts[6]
        slides = content.get("slides") or [{"titre": content.get("accroche", ""),
                                            "points": [content.get("corps", ""), content.get("cta", "")]}]
        for idx, s in enumerate(slides):
            slide = prs.slides.add_slide(blank)
            bg = slide.background.fill
            bg.solid()
            bg.fore_color.rgb = hx(self.brand.bg)
            # bande titre
            box = slide.shapes.add_shape(1, Inches(0), Inches(0), prs.slide_width, Inches(1.4))
            box.fill.solid()
            box.fill.fore_color.rgb = hx(self.brand.primary)
            box.line.fill.background()
            tf = box.text_frame
            tf.text = s.get("titre", "")
            p = tf.paragraphs[0]
            p.font.size = Pt(34); p.font.bold = True
            p.font.color.rgb = hx(self.brand.secondary)
            # puces
            content_box = slide.shapes.add_textbox(Inches(0.8), Inches(1.9), Inches(11.7), Inches(5.0))
            ctf = content_box.text_frame
            ctf.word_wrap = True
            for i, b in enumerate(s.get("points", [])):
                p = ctf.paragraphs[0] if i == 0 else ctf.add_paragraph()
                p.text = f"•  {b}"
                p.font.size = Pt(24)
                p.font.color.rgb = hx(self.brand.text)
                p.space_after = Pt(14)
            # CTA dernière slide
            if idx == len(slides) - 1 and content.get("cta"):
                cta_box = slide.shapes.add_textbox(Inches(0.8), Inches(6.3), Inches(11.7), Inches(0.8))
                p = cta_box.text_frame.paragraphs[0]
                p.text = content["cta"]
                p.font.size = Pt(22); p.font.bold = True
                p.font.color.rgb = hx(self.brand.accent)
        prs.save(str(path))
        return path


# ===========================================================================
#  4c. RENDU VIDÉO — génération IA multi-provider + fallback MoviePy
# ===========================================================================
class VideoRenderer:
    """
    Génération vidéo par IA, multi-provider choisi au runtime :
      - pollinations : gen.pollinations.ai/video (clé Pollinations)
      - fal          : fal.run (clé FAL_KEY)
      - hf           : huggingface_hub InferenceClient (HF_TOKEN)
      - moviepy      : image fixe (Pollinations) animée en mp4 (GRATUIT, sans clé)
    """

    def __init__(self, brand: Brand, image_renderer: ImageRenderer):
        self.brand = brand
        self.image = image_renderer

    def render(self, fmt: str, content: Dict[str, Any], path: Path,
               provider: str = "moviepy", duration: int = 5) -> Path:
        print(f"    [video] provider={provider}")
        if provider == "pollinations":
            if self._pollinations_video(content, path, duration):
                return path
            print("    [video] Pollinations échec -> fallback moviepy")
        if provider == "fal":
            if self._fal_video(content, path, duration):
                return path
            print("    [video] Fal échec -> fallback moviepy")
        if provider == "hf":
            if self._hf_video(content, path, duration):
                return path
            print("    [video] HuggingFace échec -> fallback moviepy")
        # fallback universel
        return self._moviepy_fallback(fmt, content, path, duration)

    # ---- Provider 1 : Pollinations vidéo (clé requise) --------------------
    def _pollinations_video(self, content: Dict[str, Any], path: Path, duration: int) -> bool:
        key = os.environ.get("POLLINATIONS_API_KEY")
        if not key:
            print("    [video] POLLINATIONS_API_KEY non définie")
            return False
        prompt = content.get("idee_visuelle", content.get("accroche", ""))
        enc = urllib.parse.quote(f"{prompt}, cinematic commercial video, 5 seconds")
        base = "https://gen.pollinations.ai"
        headers = {"Authorization": f"Bearer {key}", "User-Agent": "Wirili/2.0"}
        # 1) soumet
        try:
            req = urllib.request.Request(f"{base}/video/{enc}?model=google/veo-3.1-fast",
                                         headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                job = json.loads(r.read())
        except Exception as e:
            print(f"    [video] Pollinations submit échec : {e}")
            return False
        status_url = job.get("status_url") or f"{base}/video/status/{job.get('id')}"
        result_url = job.get("result_url") or f"{base}/video/result/{job.get('id')}"
        # 2) polling
        st: Dict[str, Any] = {}
        for _ in range(60):  # max ~15 min
            time.sleep(15)
            try:
                rq = urllib.request.Request(status_url, headers=headers)
                with urllib.request.urlopen(rq, timeout=30) as r:
                    st = json.loads(r.read())
                if st.get("status") in ("succeeded", "failed", "error"):
                    break
            except Exception:
                continue
        else:
            print("    [video] Pollinations timeout")
            return False
        if st.get("status") != "succeeded":
            print(f"    [video] Pollinations statut : {st.get('status')}")
            return False
        # 3) télécharge
        video_url = st.get("video_url") or st.get("url") or result_url
        try:
            rq = urllib.request.Request(video_url, headers=headers)
            with urllib.request.urlopen(rq, timeout=120) as r:
                path.write_bytes(r.read())
            return True
        except Exception as e:
            print(f"    [video] Pollinations download échec : {e}")
            return False

    # ---- Provider 2 : Fal.ai (clé FAL_KEY requise) ------------------------
    def _fal_video(self, content: Dict[str, Any], path: Path, duration: int) -> bool:
        key = os.environ.get("FAL_KEY")
        if not key:
            print("    [video] FAL_KEY non définie")
            return False
        model = os.environ.get("FAL_VIDEO_MODEL",
                               "fal-ai/wan/v2.2-a14b/text-to-video")
        prompt = content.get("idee_visuelle", content.get("accroche", ""))
        payload = {"prompt": f"{prompt}, cinematic commercial, {duration}s"}
        headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
        # Endpoint synchrone fal.run (queue : queue.fal.run). On tente sync d'abord.
        for base in ("https://fal.run", "https://queue.fal.run"):
            url = f"{base}/{model}"
            try:
                body = json.dumps(payload).encode()
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=600) as r:
                    data = json.loads(r.read())
                # queue : renvoie status_url / response_url
                if "status_url" in data:
                    data = self._fal_poll(data, headers)
                vurl = (data.get("video", {}) or {}).get("url") or data.get("video_url")
                if vurl:
                    req2 = urllib.request.Request(vurl)
                    with urllib.request.urlopen(req2, timeout=120) as r2:
                        path.write_bytes(r2.read())
                    return True
            except Exception as e:
                print(f"    [video] Fal ({base}) échec : {e}")
                continue
        return False

    def _fal_poll(self, data: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        status_url = data.get("status_url")
        for _ in range(80):  # max ~20 min
            time.sleep(15)
            try:
                req = urllib.request.Request(status_url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as r:
                    st = json.loads(r.read())
                if st.get("status") in ("COMPLETED", "completed", "FAILED", "failed"):
                    return st
            except Exception:
                continue
        return data

    # ---- Provider 3 : HuggingFace InferenceClient (HF_TOKEN) --------------
    def _hf_video(self, content: Dict[str, Any], path: Path, duration: int) -> bool:
        token = os.environ.get("HF_TOKEN")
        if not token:
            print("    [video] HF_TOKEN non défini")
            return False
        try:
            from huggingface_hub import InferenceClient  # type: ignore
        except Exception as e:
            print(f"    [video] huggingface_hub non installé : {e}")
            return False
        model = os.environ.get("HF_VIDEO_MODEL", "Wan-AI/Wan2.2-TI2V-5B")
        provider = os.environ.get("HF_PROVIDER", "fal-ai")
        prompt = content.get("idee_visuelle", content.get("accroche", ""))
        try:
            client = InferenceClient(provider=provider, api_key=token)
            video = client.text_to_video(f"{prompt}, cinematic commercial, {duration}s",
                                         model=model)
            # video = chemin local ou URL
            if isinstance(video, str) and video.startswith("http"):
                req = urllib.request.Request(video)
                with urllib.request.urlopen(req, timeout=120) as r:
                    path.write_bytes(r.read())
            else:
                data = video if isinstance(video, (bytes, bytearray)) else open(video, "rb").read()
                path.write_bytes(data)
            return True
        except Exception as e:
            print(f"    [video] HuggingFace échec : {e}")
            return False

    # ---- Fallback : MoviePy (image fixe -> mp4, GRATUIT, sans clé) --------
    def _moviepy_fallback(self, fmt: str, content: Dict[str, Any], path: Path,
                          duration: int) -> Path:
        try:
            from moviepy import ImageClip  # type: ignore  # moviepy >= 2.0
        except Exception:
            try:
                from moviepy.editor import ImageClip  # type: ignore  # moviepy < 2.0
            except Exception as e:
                raise RuntimeError(
                    "MoviePy non installé (pip install moviepy) ET aucun provider vidéo "
                    f"disponible. Installez moviepy ou configurez une clé provider.\n  {e}"
                )
        # 1) génère une image (Pollinations gratuit ou Pillow)
        tmp_img = path.with_suffix(".png")
        self.image.render(fmt, content, tmp_img)
        # 2) image -> vidéo (zoom subtil Ken Burns pour un peu de vie)
        clip = ImageClip(str(tmp_img))
        # moviepy >= 2.0 (API v2) vs < 2.0 (API v1)
        clip = clip.with_duration(duration) if hasattr(clip, "with_duration") \
            else clip.set_duration(duration)
        try:  # zoom progressif optionnel (Ken Burns)
            zoom = lambda t: 1 + 0.04 * t / duration
            clip = clip.resized(zoom) if hasattr(clip, "resized") \
                else clip.resize(zoom)
        except Exception:
            pass
        clip.write_videofile(str(path), fps=24, codec="libx264",
                             audio=False, logger=None)
        if tmp_img.exists():
            tmp_img.unlink()
        print(f"    [video] MoviePy fallback OK ({duration}s)")
        return path


# ===========================================================================
#  5. EXPORTER
# ===========================================================================
class Exporter:
    def __init__(self, brand: Brand, root: Path):
        self.brand = brand
        self.out_dir = root / "output" / self._slug(brand.name)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.assets = self.out_dir / "assets"
        self.assets.mkdir(exist_ok=True)
        self.text_dir = self.out_dir / "text"
        self.text_dir.mkdir(exist_ok=True)

    @staticmethod
    def _slug(name: str) -> str:
        s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
        return s or "brand"

    def save_copy(self, fmt: str, content: Dict[str, Any]) -> Path:
        path = self.text_dir / f"{fmt}.txt"
        if fmt == "slides":
            text = "\n\n".join(f"## {s.get('titre','')}\n" + "\n".join(f"- {p}" for p in s.get("points", []))
                               for s in content.get("slides", []))
        else:
            tags = " ".join("#" + h for h in content.get("hashtags", []))
            text = f"{content.get('accroche','')}\n\n{content.get('corps','')}\n\n{content.get('cta','')}\n\n{tags}"
        path.write_text(text.strip(), encoding="utf-8")
        return path

    def asset_path(self, fmt: str, ext: str) -> Path:
        return self.assets / f"{fmt}.{ext}"

    def write_manifest(self, brief: str, results: List[Dict[str, Any]]) -> Path:
        manifest = {
            "agent": "Wirili",
            "version": "2.0",
            "brand": asdict(self.brand),
            "brief": brief,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "formats": results,
        }
        path = self.out_dir / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


# ===========================================================================
#  ORCHESTRATEUR
# ===========================================================================
class Wirili:
    def __init__(self, brand: Brand, workdir: Path, video_provider: str = "moviepy"):
        self.brand = brand
        self.workdir = workdir
        self.video_provider = video_provider
        self.llm = LLMProvider()
        self.router = Router(FORMATS)
        self.copy = CopyAgent(self.llm, brand)
        self.validator = Validator()
        self.image = ImageRenderer(brand)
        self.slides = SlidesRenderer(brand)
        self.video = VideoRenderer(brand, self.image)
        self.exporter = Exporter(brand, workdir)

    def run(self, brief: str, requested: Optional[List[str]] = None) -> Path:
        print(f"[Wirili v2] Marque : {self.brand.name}")
        print(f"[Wirili v2] LLM : {self.llm.mode}")
        print(f"[Wirili v2] Vidéo provider : {self.video_provider}")
        formats = self.router.select(requested, brief)
        print(f"[Wirili v2] Formats : {', '.join(formats)}\n")

        results: List[Dict[str, Any]] = []
        for fmt in formats:
            print(f"— Format : {fmt} ({FORMATS[fmt].get('render', '?')})")
            content = self._produce_valid(fmt, brief)
            self.exporter.save_copy(fmt, content)
            entry: Dict[str, Any] = {"format": fmt, "copy": content,
                                     "files": {"text": str(self.exporter.text_dir / f"{fmt}.txt")}}
            try:
                self._render(fmt, content, entry)
            except Exception as e:
                print(f"  ⚠️  Rendu {fmt} échoué : {e}")
                entry["error"] = str(e)
            results.append(entry)
            print()

        manifest = self.exporter.write_manifest(brief, results)
        print(f"[Wirili v2] Terminé. Manifest : {manifest}")
        return manifest

    def _produce_valid(self, fmt: str, brief: str) -> Dict[str, Any]:
        content = self.copy.write(fmt, brief)
        for attempt in range(Validator.MAX_RETRIES):
            errs = self.validator.validate(fmt, content)
            if not errs:
                print(f"  ✓ Validation OK (tentative {attempt + 1})")
                return content
            print(f"  ⚠️  Validation (tentative {attempt + 1}) : {errs}")
            content = self.copy.write(fmt, brief, errs)
        # force-fit dernier recours
        content = self._force_fit(fmt, content)
        print(f"  ✓ Conformité forcée.")
        return content

    def _force_fit(self, fmt: str, content: Dict[str, Any]) -> Dict[str, Any]:
        spec = FORMATS[fmt]
        if len(content.get("hashtags", [])) > spec["max_hashtags"]:
            content["hashtags"] = content["hashtags"][:spec["max_hashtags"]]
        if fmt == "slides":
            sl = content.get("slides", [])
            if len(sl) > spec["max_slides"]:
                content["slides"] = sl[:spec["max_slides"]]
        else:
            total = (len(content.get("accroche", "")) + len(content.get("corps", ""))
                     + len(content.get("cta", "")))
            if total > spec["max_chars"]:
                overflow = total - spec["max_chars"]
                content["corps"] = content.get("corps", "")[:max(0, len(content.get("corps", "")) - overflow - 1)] + "…"
        return content

    def _render(self, fmt: str, content: Dict[str, Any], entry: Dict[str, Any]) -> None:
        render = FORMATS[fmt]["render"]
        if render == "slides":
            out = self.exporter.asset_path(fmt, "pptx")
            self.slides.render(content, out)
            entry["files"]["slides"] = str(out)
            print(f"  ✓ Slides → {out.name}")
        elif render == "video":
            out = self.exporter.asset_path(fmt, "mp4")
            duration = FORMATS[fmt].get("max_duration", 5)
            self.video.render(fmt, content, out, self.video_provider, duration)
            entry["files"]["video"] = str(out)
            print(f"  ✓ Vidéo → {out.name}")
        else:  # image
            out = self.exporter.asset_path(fmt, "png")
            self.image.render(fmt, content, out)
            entry["files"]["image"] = str(out)
            print(f"  ✓ Image → {out.name}")


# ===========================================================================
#  CLI
# ===========================================================================
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="wirili", description="Wirili — agent publicitaire autonome v2.")
    p.add_argument("brief", help="Brief de campagne.")
    p.add_argument("--brand", default="Lumina Glow")
    p.add_argument("--formats", nargs="*", default=None,
                   help=f"Formats : {', '.join(FORMATS)}. Auto si omis.")
    p.add_argument("--workdir", default=".")
    p.add_argument("--voice", default=None, help="Surcharge le ton de voix.")
    p.add_argument("--language", default=None, help="Langue du copy (déf. français).")
    p.add_argument("--logo", default=None, help="Logo PNG transparent overlay sur les visuels.")
    p.add_argument("--primary", default=None, help="Couleur principale (hex, ex. #0F2A2A).")
    p.add_argument("--accent", default=None, help="Couleur accent CTA (hex, ex. #F5A65B).")
    p.add_argument("--no-overlay", action="store_true",
                   help="Désactive l'overlay de marque sur les images IA.")
    p.add_argument("--video-provider", default="moviepy",
                   choices=["moviepy", "pollinations", "fal", "hf"],
                   help="Provider vidéo (déf. moviepy = gratuit sans clé).")
    args = p.parse_args(argv)

    brand = Brand(name=args.brand)
    if args.voice:
        brand.tone = args.voice
    if args.language:
        brand.language = args.language
    if args.logo:
        brand.logo_path = args.logo
    if args.primary:
        brand.primary = args.primary
    if args.accent:
        brand.accent = args.accent
    if args.no_overlay:
        brand.overlay_enabled = False

    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    agent = Wirili(brand, workdir, video_provider=args.video_provider)
    agent.run(args.brief, args.formats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
