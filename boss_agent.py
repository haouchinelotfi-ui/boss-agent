# -*- coding: utf-8 -*-
"""
BOSS AGENT - manager qui planifie, distribue, contrôle, répare et livre

Tourne en LOCAL sous FreeLLMAPI (http://127.0.0.1:31415), routeur LLM gratuit.
Aucune clé Anthropic requise. La clé unifiée FreeLLMAPI est lue automatiquement
dans sa DB SQLite (%APPDATA%/FreeLLMAPI/freeapi.db), ou via FREELLMAPI_KEY /
FREELLMAPI_BASE. model="auto" = routage intelligent parmi ~280 modèles.

ARCHITECTURE
============
Mission (texte libre)
   →
   ┌──────────────────────────── BOSS ────────────────────────────┐
   │ 1. Planner      -> découpe en tâches + dépendances (DAG)     │
   │ 2. Dispatcher   -> assigne chaque tâche au bon agent         │
   │ 3. Exécution    -> en parallèle quand les tâches sont        │
   │                    indépendantes                             │
   │ 4. Contrôle     -> validation technique + revue qualité      │
   │ 5. DOCTEUR      -> maintenance et réparation :               │
   │      - panne transitoire  : retry avec backoff               │
   │      - livrable défaillant: renvoi avec feedback précis      │
   │      - code qui plante    : exécution test + correction      │
   │      - agent en échec     : coupe-circuit + agent de         │
   │                             secours                          │
   │      - échec persistant   : escalade vers l'humain           │
   │ 6. Rapport      -> livrables + incidents + audit             │
   └──────────────────────────────────────────────────────────────┘
        ↓ délègue à
        Agents exécutants (rédaction, code, données, design, pub...)

SÉCURITÉ : le Boss détient TOUS les droits (Scope), mais les actions
irréversibles (supprimer, envoyer à l'extérieur, dépenser) exigent une
approbation humaine. Tout est tracé dans audit.jsonl.

Installation : pip install requests   (anthropic N'EST PLUS nécessaire)
Lancement    : python boss_agent.py "Prépare le dossier de lancement ..."
              (FreeLLMAPI doit tourner sur 127.0.0.1:31415)
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

# Forcer la console en UTF-8 (Windows cp1252 ne gère pas ✓ ⚠ …).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

MODEL = os.environ.get("FREELLMAPI_MODEL", "auto")
MAX_ATTEMPTS = 4
BREAKER_THRESHOLD = 3
FREELLMAPI_BASE = os.environ.get("FREELLMAPI_BASE", "http://127.0.0.1:31415").rstrip("/")


# -------------------------------------------------------------------------- #
#  LECTURE DE LA CLÉ UNIFIÉE FreeLLMAPI
# -------------------------------------------------------------------------- #
def _read_freellm_key() -> str | None:
    """Clé unifiée FreeLLMAPI : env > DB SQLite > None."""
    key = os.environ.get("FREELLMAPI_KEY") or os.environ.get("UNIFIED_API_KEY")
    if key:
        return key
    try:
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


# -------------------------------------------------------------------------- #
#  1. LLM  — FreeLLMAPI (OpenAI-compatible), gratuit, local
# -------------------------------------------------------------------------- #
class LLMError(Exception):
    """Erreur générique du LLM (englobe réseau, rate-limit, format)."""


class RateLimitError(LLMError):
    """Limite de débit / modèles épuisés (transitoire)."""


class ConnectionErrorLLM(LLMError):
    """Panne réseau / endpoint injoignable (transitoire)."""


class LLM:
    """Client OpenAI-compatible vers FreeLLMAPI local."""

    def __init__(self, base: str = FREELLMAPI_BASE, model: str = MODEL) -> None:
        self.base = base.rstrip("/")
        self.model = model
        self.api_key = _read_freellm_key() or "freellmapi"
        self.timeout = int(os.environ.get("FREELLMAPI_TIMEOUT", "180"))

    # --- requête HTTP bas niveau ---
    def _post_chat(self, messages: list[dict], max_tokens: int) -> str:
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        url = f"{self.base}/v1/chat/completions"
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:800]
            except Exception:
                pass
            msg = f"HTTP {e.code} {e.reason} | {body}"
            # 429 / 503 / rate_limit_error => transitoire
            low = body.lower()
            if e.code in (429, 503) or "rate_limit" in low or "exhausted" in low \
                    or "cooldown" in low or "service_unavailable" in low:
                raise RateLimitError(msg) from None
            raise LLMError(msg) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise ConnectionErrorLLM(f"endpoint {url} injoignable : {e}") from None

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"réponse FreeLLMAPI mal formée : {data}") from e

    # --- API haut niveau ---
    def text(self, system: str, user: str, max_tokens: int = 4000) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        return self._post_chat(messages, max_tokens).strip()

    def json(self, system: str, user: str, max_tokens: int = 3000) -> dict:
        raw = self.text(
            system + "\nRéponds UNIQUEMENT en JSON valide, sans markdown ni texte autour.",
            user, max_tokens,
        )
        return _parse_json(raw)

    def ping(self) -> bool:
        try:
            self.text("Réponds ok.", "ping", 5)
            return True
        except Exception:
            return False


def _parse_json(raw: str) -> dict:
    raw = raw.strip().strip("`")
    if raw.lower().startswith("json"):
        raw = raw[4:].strip()
    s = raw.find("{")
    e = raw.rfind("}")
    if s != -1 and e != -1 and e > s:
        raw = raw[s:e + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise LLMError(f"JSON invalide : {e} | extrait : {raw[:300]}") from None


def strip_fences(s: str) -> str:
    s = s.strip()
    for tag in ("```python", "```json", "```"):
        s = s.removeprefix(tag)
    return s.removesuffix("```").strip()


# -------------------------------------------------------------------------- #
#  2. PERMISSIONS + AUDIT
# -------------------------------------------------------------------------- #
class Scope(str, Enum):
    READ = "read_files"
    WRITE = "write_files"
    EXEC = "exec_code"
    NETWORK = "network"
    DELETE = "delete"
    SEND = "send_external"
    SPEND = "spend_money"


IRREVERSIBLE = {Scope.DELETE, Scope.SEND, Scope.SPEND}


class PermissionDenied(Exception):
    pass


class Audit:
    def __init__(self, path: Path) -> None:
        self.path = path

    def log(self, event: str, **data) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%F %T"), "event": event, **data},
                               ensure_ascii=False) + "\n")


def human_approver(actor: str, scope: Scope, detail: str) -> bool:
    return input(f"[APPROBATION] {actor} demande {scope.value} : {detail} (o/N) ").lower() == "o"


class Permissions:
    def __init__(self, audit: Audit, approver: Callable = human_approver) -> None:
        self.audit, self.approver = audit, approver
        self.grants: dict[str, set[Scope]] = {}

    def grant(self, actor: str, scopes: set[Scope]) -> None:
        self.grants[actor] = scopes

    def check(self, actor: str, scope: Scope, detail: str = "") -> None:
        if scope not in self.grants.get(actor, set()):
            self.audit.log("denied", actor=actor, scope=scope.value, detail=detail)
            raise PermissionDenied(f"{actor} n'a pas le droit {scope.value}")
        if scope in IRREVERSIBLE and not self.approver(actor, scope, detail):
            self.audit.log("refused_by_human", actor=actor, scope=scope.value, detail=detail)
            raise PermissionDenied(f"Action irréversible refusée : {scope.value}")
        self.audit.log("allowed", actor=actor, scope=scope.value, detail=detail)


# -------------------------------------------------------------------------- #
#  3. MODÈLES DE DONNÉES
# -------------------------------------------------------------------------- #
@dataclass
class Deliverable:
    kind: str            # text | python | json | file
    content: str = ""
    path: str | None = None


@dataclass
class Task:
    id: str
    title: str
    role: str
    instructions: str
    acceptance: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    kind: str = "text"
    status: str = "pending"   # pending | done | escalated
    attempts: int = 0
    result: Deliverable | None = None


# -------------------------------------------------------------------------- #
#  4. AGENTS EXÉCUTANTS
# -------------------------------------------------------------------------- #
class Worker:
    """Agent générique piloté par un rôle (prompt système)."""

    def __init__(self, role: str, system: str, llm: LLM) -> None:
        self.role, self.system, self.llm = role, system, llm

    def execute(self, task: Task, context: dict[str, Deliverable],
                feedback: list[str], previous: Deliverable | None) -> Deliverable:
        ctx = "\n".join(f"[{k}] {v.content[:1500]}" for k, v in context.items()
                        if k in task.depends_on)
        prompt = (f"Tâche : {task.title}\nConsignes : {task.instructions}\n"
                  f"Critères d'acceptation : {task.acceptance}\n"
                  f"Résultats des tâches précédentes :\n{ctx or '(aucun)'}\n")
        if previous and feedback:
            prompt += (f"\nVERSION PRÉCÉDENTE :\n{previous.content}\n"
                       f"PROBLÈMES À CORRIGER :\n- " + "\n- ".join(feedback) +
                       "\nRenvoie la version COMPLÈTE corrigée.")
        if task.kind in ("python", "json"):
            prompt += f"\nRenvoie uniquement du {task.kind} brut, sans explication."
        out = self.llm.text(self.system, prompt)
        return Deliverable(kind=task.kind, content=strip_fences(out) if task.kind != "text" else out)


class CallableWorker(Worker):
    """Branche un agent existant (ex. Wirili de agent_pub.py)."""

    def __init__(self, role: str, fn: Callable[[Task], Deliverable]) -> None:
        self.role, self.fn = role, fn

    def execute(self, task, context, feedback, previous) -> Deliverable:
        return self.fn(task)


DEFAULT_ROLES = {
    "redacteur": "Rédacteur professionnel : textes clairs, structurés, sans fautes.",
    "developpeur": "Développeur senior Python : code propre, complet, exécutable, commenté.",
    "analyste": "Analyste données : chiffres vérifiables, hypothèses explicites, JSON si demandé.",
    "designer": "Directeur artistique : descriptions de maquettes précises (couleurs, grille, textes).",
    "generaliste": "Expert polyvalent capable de traiter tout type de livrable.",
}


# -------------------------------------------------------------------------- #
#  5. CONTRÔLE QUALITÉ
# -------------------------------------------------------------------------- #
def validate(d: Deliverable) -> list[str]:
    """Contrôles techniques déterministes."""
    errs: list[str] = []
    if d.kind == "file":
        if not d.path or not Path(d.path).exists():
            errs.append(f"fichier introuvable : {d.path}")
        return errs
    if not d.content.strip():
        return ["livrable vide"]
    if d.kind == "json":
        try:
            json.loads(d.content)
        except json.JSONDecodeError as e:
            errs.append(f"JSON invalide : {e}")
    if d.kind == "python":
        try:
            compile(d.content, "<livrable>", "exec")
        except SyntaxError as e:
            errs.append(f"erreur de syntaxe ligne {e.lineno} : {e.msg}")
    return errs


class Reviewer:
    """Revue qualité par LLM, face aux critères d'acceptation."""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def review(self, task: Task, d: Deliverable) -> list[str]:
        if not task.acceptance:
            return []
        out = self.llm.json(
            "Tu es un contrôleur qualité exigeant mais juste.",
            f"Critères : {task.acceptance}\nLivrable :\n{d.content[:6000]}\n"
            'Format : {"ok": true/false, "problemes": ["..."]}',
        )
        return [] if out.get("ok") else out.get("problemes", ["non conforme"])


# -------------------------------------------------------------------------- #
#  6. MODULE DE MAINTENANCE ET RÉPARATION (DOCTEUR)
# -------------------------------------------------------------------------- #
class Doctor:
    TRANSIENT = (RateLimitError, ConnectionErrorLLM, TimeoutError, ConnectionError)

    def __init__(self, audit: Audit, perms: Permissions, run_dir: Path) -> None:
        self.audit, self.perms, self.run_dir = audit, perms, run_dir
        self.failures: dict[str, int] = {}
        self.incidents: list[dict] = []

    # --- diagnostic ---
    def diagnose(self, exc: Exception) -> str:
        if isinstance(exc, PermissionDenied):
            return "permission"
        if isinstance(exc, self.TRANSIENT):
            return "transient"
        if isinstance(exc, (json.JSONDecodeError, LLMError)):
            return "format"
        return "unknown"

    def incident(self, task: Task, kind: str, detail: str) -> None:
        rec = {"task": task.id, "type": kind, "detail": detail[:500], "attempt": task.attempts}
        self.incidents.append(rec)
        self.audit.log("incident", **rec)

    # --- stratégies de réparation ---
    @staticmethod
    def backoff(attempt: int) -> None:
        time.sleep(min(2 ** attempt, 30))

    def smoke_test(self, d: Deliverable, actor: str) -> list[str]:
        """Exécute le code produit dans un sous-processus isolé avec timeout."""
        self.perms.check(actor, Scope.EXEC, "smoke test code livrable")
        f = self.run_dir / f"smoke_{uuid.uuid4().hex[:6]}.py"
        f.write_text(d.content, encoding="utf-8")
        try:
            r = subprocess.run([sys.executable, str(f)], capture_output=True,
                               text=True, timeout=20, cwd=self.run_dir)
            if r.returncode != 0:
                return [f"le code plante à l'exécution :\n{r.stderr[-1500:]}"]
        except subprocess.TimeoutExpired:
            return ["le code dépasse 20 s (boucle infinie ou attente bloquante ?)"]
        finally:
            f.unlink(missing_ok=True)
        return []

    # --- coupe-circuit ---
    def record(self, role: str, ok: bool) -> None:
        self.failures[role] = 0 if ok else self.failures.get(role, 0) + 1

    def is_open(self, role: str) -> bool:
        return self.failures.get(role, 0) >= BREAKER_THRESHOLD

    # --- contrôle de santé ---
    def health_check(self, llm: LLM) -> dict:
        h = {"disque": False, "llm": False, "llm_mode": "freellmapi"}
        try:
            (self.run_dir / ".ping").write_text("ok")
            h["disque"] = True
        except Exception as e:
            self.audit.log("health_fail", error=str(e))
            return h
        try:
            h["llm"] = llm.ping()
        except Exception as e:
            self.audit.log("health_fail", error=str(e))
        return h


# -------------------------------------------------------------------------- #
#  7. LE BOSS
# -------------------------------------------------------------------------- #
class Boss:
    NAME = "boss"

    def __init__(self, approver: Callable = human_approver, base_dir: str = "runs",
                 llm: LLM | None = None) -> None:
        self.run_id = time.strftime("%Y%m%d_%H%M%S")
        self.run_dir = (Path(base_dir) / self.run_id).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.audit = Audit(self.run_dir / "audit.jsonl")
        self.perms = Permissions(self.audit, approver)
        self.perms.grant(self.NAME, set(Scope))                      # tous les droits
        self.llm = llm or LLM()
        self.doctor = Doctor(self.audit, self.perms, self.run_dir)
        self.reviewer = Reviewer(self.llm)
        self.workers: dict[str, Worker] = {}
        for role, system in DEFAULT_ROLES.items():
            # developpeur ET generaliste (fallback du developpeur) ont droit EXEC
            # pour le smoke test du code produit.
            scopes = ({Scope.READ, Scope.WRITE, Scope.EXEC}
                      if role in ("developpeur", "generaliste")
                      else {Scope.READ, Scope.WRITE})
            self.register(Worker(role, system, self.llm), scopes)

    def register(self, worker: Worker, scopes: set[Scope]) -> None:
        self.workers[worker.role] = worker
        self.perms.grant(worker.role, scopes)

    # --- 1. planification ---
    def plan(self, mission: str) -> list[Task]:
        out = self.llm.json(
            "Tu es un chef de projet expert. Découpe la mission en tâches atomiques. "
            f"Rôles disponibles : {list(self.workers)}. Types de livrable : text, python, json.",
            f"Mission : {mission}\nFormat : {{\"tasks\": [{{\"id\":\"t1\",\"title\":\"\","
            "\"role\":\"\",\"instructions\":\"\",\"kind\":\"text\","
            "\"acceptance\":[\"\"],\"depends_on\":[]}]}}",
            4000,
        )
        tasks = [Task(**{k: v for k, v in t.items() if k in Task.__dataclass_fields__})
                 for t in out["tasks"]]
        for t in tasks:
            if t.role not in self.workers:
                t.role = "generaliste"
        self.audit.log("plan", tasks=[t.id for t in tasks])
        return tasks

    # --- 2. exécution d'une tâche avec boucle de réparation ---
    def _run_task(self, task: Task, ctx: dict[str, Deliverable]) -> None:
        worker = self.workers[task.role]
        original_role = task.role
        feedback: list[str] = []
        previous: Deliverable | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            task.attempts = attempt
            # Coupe-circuit : on ne bascule vers le généraliste QUE pour les
            # rôles internes pilotés par LLM (Worker). Pour les agents externes
            # (CallableWorker, ex. Wirili) le généraliste ne sait pas produire
            # le même type de livrable, on garde donc le worker original.
            if self.doctor.is_open(original_role) and \
                    not isinstance(self.workers[original_role], CallableWorker):
                self.audit.log("fallback", task=task.id, from_role=original_role)
                worker = self.workers["generaliste"]
            try:
                d = worker.execute(task, ctx, feedback, previous)
                issues = validate(d)
                if not issues and d.kind == "python":
                    issues = self.doctor.smoke_test(d, worker.role)
                # Revue qualité LLM uniquement pour les livrables textuels
                # (text/python/json). Un livrable 'file' (dossier d'assets,
                # images, pptx) est validé techniquement ci-dessus ; les
                # critères d'acceptation textuels du planner ne s'y appliquent
                # pas et généreraient de faux négatifs.
                if not issues and d.kind != "file":
                    issues = self.reviewer.review(task, d)
                if not issues:
                    task.status, task.result = "done", d
                    self.doctor.record(original_role, True)
                    self.audit.log("task_done", task=task.id, attempts=attempt)
                    return
                self.doctor.record(original_role, False)
                self.doctor.incident(task, "livrable_non_conforme", "; ".join(issues))
                feedback, previous = issues, d                       # renvoi avec feedback
            except Exception as e:
                kind = self.doctor.diagnose(e)
                self.doctor.incident(task, kind, f"{e}\n{traceback.format_exc()[-400:]}")
                if kind == "permission":
                    break                                            # escalade immédiate
                self.doctor.record(original_role, False)
                if kind == "transient":
                    self.doctor.backoff(attempt)
                else:
                    feedback = [f"exception : {e}"]

        task.status = "escalated"                                    # échec persistant
        self.audit.log("escalated", task=task.id)

    # --- 3. orchestration ---
    def run(self, mission: str) -> dict:
        health = self.doctor.health_check(self.llm)
        if not health.get("llm"):
            return {"erreur": "FreeLLMAPI injoignable sur "
                     f"{self.llm.base} — démarrez FreeLLMAPI puis relancez.",
                    "sante": health}
        if not health.get("disque"):
            return {"erreur": "contrôle de santé échoué", "sante": health}

        tasks = self.plan(mission)
        ctx: dict[str, Deliverable] = {}
        pending = {t.id: t for t in tasks}

        while pending:
            ready = [t for t in pending.values()
                     if all(d in ctx for d in t.depends_on)]
            blocked = not ready
            if blocked:                                              # dépendance en échec
                for t in pending.values():
                    t.status = "escalated"
                break
            with ThreadPoolExecutor(max_workers=4) as pool:          # parallélisme
                list(pool.map(lambda t: self._run_task(t, ctx), ready))
            for t in ready:
                pending.pop(t.id)
                if t.status == "done" and t.result:
                    ctx[t.id] = t.result
            self._checkpoint(tasks)

        return self._report(mission, tasks)

    # --- 4. livraison ---
    def _checkpoint(self, tasks: list[Task]) -> None:
        (self.run_dir / "state.json").write_text(
            json.dumps([asdict(t) for t in tasks], ensure_ascii=False, indent=2),
            encoding="utf-8")

    def _report(self, mission: str, tasks: list[Task]) -> dict:
        self.perms.check(self.NAME, Scope.WRITE, "écriture des livrables")
        ext = {"python": "py", "json": "json", "text": "md"}
        files = []
        for t in tasks:
            if t.result and t.result.kind != "file":
                p = self.run_dir / f"{t.id}_{t.role}.{ext.get(t.result.kind, 'txt')}"
                p.write_text(t.result.content, encoding="utf-8")
                files.append(str(p))
            elif t.result and t.result.path:
                files.append(t.result.path)
        report = {
            "mission": mission,
            "statut": "complet" if all(t.status == "done" for t in tasks) else "partiel",
            "taches": {t.id: {"titre": t.title, "role": t.role,
                              "statut": t.status, "essais": t.attempts} for t in tasks},
            "a_traiter_par_humain": [t.id for t in tasks if t.status == "escalated"],
            "incidents": self.doctor.incidents,
            "livrables": files,
        }
        (self.run_dir / "rapport.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report


if __name__ == "__main__":
    mission = " ".join(sys.argv[1:]) or \
        "Écris un script Python qui calcule une moyenne et rédige sa notice."
    print(json.dumps(Boss().run(mission), ensure_ascii=False, indent=2))
