# -*- coding: utf-8 -*-
"""
Tests unitaires du Boss Agent — sans réseau, sans FreeLLMAPI.

Couvre :
  - _parse_json (extraction JSON robuste)
  - strip_fences (retrait des markdown fences)
  - validate (text / python / json / file)
  - Permissions (scopes, actions irréversibles, audit)
  - Doctor (diagnose, smoke_test, coupe-circuit)
  - Boss.plan (mock LLM, routage rôle inconnu → generaliste)
  - Boss.run (orchestration complète avec LLM mocké, escalade)
  - CallableWorker (branchement d'un agent externe)

Lancement : python -m pytest test_boss.py -v
           (ou : python test_boss.py  → mode autonome sans pytest)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# boss_agent.py est dans le même dossier.
sys.path.insert(0, str(Path(__file__).parent))
from boss_agent import (
    Audit, Boss, CallableWorker, ConnectionErrorLLM, Deliverable, Doctor,
    LLM, LLMError, Permissions, PermissionDenied, RateLimitError, Reviewer,
    Scope, Task, Worker, _parse_json, strip_fences, validate,
)
from dataclasses import asdict


# --------------------------------------------------------------------------- #
#  Fixtures : un LLM mocké qui ne touche jamais le réseau
# --------------------------------------------------------------------------- #
class FakeLLM(LLM):
    """LLM de test : renvoie des réponses programmées sans aucun appel réseau."""

    def __init__(self, json_map=None, text_map=None, default_text="ok",
                 ping_ok=True):
        # On court-circuite LLM.__init__ (qui lit la clé FreeLLMAPI).
        self.base = "http://fake"
        self.model = "fake-model"
        self._json_map = json_map or {}
        self._text_map = text_map or {}
        self._default_text = default_text
        self._ping_ok = ping_ok
        self.text_calls = []  # journal des appels pour inspection
        # run() appelle self.llm._health.clear() lors du retry de health check.
        self._health = {}

    def text(self, system, user, max_tokens=4000):
        self.text_calls.append((system[:40], user[:60]))
        # Si une réponse JSON est attendue pour ce prompt, on la renvoie brute.
        for key, val in self._json_map.items():
            if key in user:
                return val if isinstance(val, str) else json.dumps(val)
        for key, val in self._text_map.items():
            if key in user:
                return val
        return self._default_text

    def json(self, system, user, max_tokens=3000):
        raw = self.text(system + "\nJSON", user, max_tokens)
        return _parse_json(raw)

    def ping(self):
        return self._ping_ok


@pytest.fixture
def tmp_runs(tmp_path):
    """Retourne un Boss avec un dossier de run temporaire et un FakeLLM."""
    boss = Boss(approver=lambda *a: True, base_dir=str(tmp_path),
                llm=FakeLLM(ping_ok=True))
    return boss


# --------------------------------------------------------------------------- #
#  1. _parse_json — extraction robuste
# --------------------------------------------------------------------------- #
class TestParseJson:
    def test_json_pur(self):
        assert _parse_json('{"a": 1}') == {"a": 1}

    def test_json_avec_texte_autour(self):
        raw = 'Voici le plan :\n{"tasks": []}\nFin.'
        assert _parse_json(raw) == {"tasks": []}

    def test_json_avec_fences(self):
        raw = '```json\n{"x": 2}\n```'
        assert _parse_json(raw) == {"x": 2}

    def test_json_prefixe_json(self):
        assert _parse_json('json {"k": "v"}') == {"k": "v"}

    def test_json_invalide_leve_llmerror(self):
        with pytest.raises(LLMError):
            _parse_json("pas du tout du json")


# --------------------------------------------------------------------------- #
#  2. strip_fences
# --------------------------------------------------------------------------- #
class TestStripFences:
    def test_python_fence(self):
        assert strip_fences("```python\nprint(1)\n```") == "print(1)"

    def test_json_fence(self):
        assert strip_fences("```json\n{}\n```") == "{}"

    def test_plain_fence(self):
        assert strip_fences("```\ncode\n```") == "code"

    def test_sans_fence(self):
        assert strip_fences("brut") == "brut"


# --------------------------------------------------------------------------- #
#  3. validate — contrôles techniques par type de livrable
# --------------------------------------------------------------------------- #
class TestValidate:
    def test_text_ok(self):
        assert validate(Deliverable(kind="text", content="hello")) == []

    def test_text_vide(self):
        assert validate(Deliverable(kind="text", content="   ")) == ["livrable vide"]

    def test_json_valide(self):
        assert validate(Deliverable(kind="json", content='{"a":1}')) == []

    def test_json_invalide(self):
        errs = validate(Deliverable(kind="json", content="{bad"))
        assert len(errs) == 1 and "JSON" in errs[0]

    def test_python_valide(self):
        assert validate(Deliverable(kind="python", content="print(1)")) == []

    def test_python_syntaxe_erreur(self):
        errs = validate(Deliverable(kind="python", content="def("))
        assert len(errs) == 1 and "syntaxe" in errs[0]

    def test_file_existant(self, tmp_path):
        f = tmp_path / "out.txt"
        f.write_text("x")
        assert validate(Deliverable(kind="file", path=str(f))) == []

    def test_file_introuvable(self):
        errs = validate(Deliverable(kind="file", path="/nope/missing.txt"))
        assert len(errs) == 1 and "introuvable" in errs[0]


# --------------------------------------------------------------------------- #
#  4. Permissions — scopes, irréversibles, audit
# --------------------------------------------------------------------------- #
class TestPermissions:
    def _make(self, approver=lambda *a: True, tmp_path=None):
        audit = Audit((tmp_path or Path("/tmp")) / "audit.jsonl")
        return Permissions(audit, approver)

    def test_scope_autorise_passe(self, tmp_path):
        p = self._make(tmp_path=tmp_path)
        p.grant("bob", {Scope.READ})
        p.check("bob", Scope.READ, "lecture")  # ne lève pas

    def test_scope_non_autorise_leve(self, tmp_path):
        p = self._make(tmp_path=tmp_path)
        p.grant("bob", {Scope.READ})
        with pytest.raises(PermissionDenied):
            p.check("bob", Scope.WRITE, "écriture")

    def test_action_irreversible_refusee(self, tmp_path):
        p = self._make(approver=lambda *a: False, tmp_path=tmp_path)
        p.grant("bob", {Scope.DELETE})
        with pytest.raises(PermissionDenied):
            p.check("bob", Scope.DELETE, "supprimer fichier")

    def test_action_irreversible_approuvee(self, tmp_path):
        p = self._make(approver=lambda *a: True, tmp_path=tmp_path)
        p.grant("bob", {Scope.DELETE})
        p.check("bob", Scope.DELETE, "supprimer")  # ne lève pas

    def test_audit_trace_refus(self, tmp_path):
        log = tmp_path / "audit.jsonl"
        p = Permissions(Audit(log), approver=lambda *a: False)
        p.grant("bob", {Scope.SEND})
        try:
            p.check("bob", Scope.SEND, "envoi")
        except PermissionDenied:
            pass
        contenu = log.read_text(encoding="utf-8")
        assert "refused_by_human" in contenu


# --------------------------------------------------------------------------- #
#  5. Doctor — diagnose, smoke_test, coupe-circuit
# --------------------------------------------------------------------------- #
class TestDoctor:
    def _make(self, tmp_path):
        audit = Audit(tmp_path / "audit.jsonl")
        perms = Permissions(audit, lambda *a: True)
        perms.grant("dev", {Scope.EXEC})
        return Doctor(audit, perms, tmp_path)

    def test_diagnose_permission(self, tmp_path):
        d = self._make(tmp_path)
        assert d.diagnose(PermissionDenied("nope")) == "permission"

    def test_diagnose_transient_ratelimit(self, tmp_path):
        assert self._make(tmp_path).diagnose(RateLimitError("429")) == "transient"

    def test_diagnose_transient_connexion(self, tmp_path):
        assert self._make(tmp_path).diagnose(ConnectionErrorLLM("down")) == "transient"

    def test_diagnose_format(self, tmp_path):
        assert self._make(tmp_path).diagnose(json.JSONDecodeError("x", "doc", 0)) == "format"

    def test_diagnose_unknown(self, tmp_path):
        assert self._make(tmp_path).diagnose(ValueError("??")) == "unknown"

    def test_smoke_test_code_ok(self, tmp_path):
        d = self._make(tmp_path)
        errs = d.smoke_test(Deliverable(kind="python", content="print(1+1)"), "dev")
        assert errs == []

    def test_smoke_test_code_plante(self, tmp_path):
        d = self._make(tmp_path)
        errs = d.smoke_test(
            Deliverable(kind="python", content="raise RuntimeError('boom')"), "dev")
        assert errs and "plante" in errs[0]

    def test_smoke_test_timeout(self, tmp_path):
        d = self._make(tmp_path)
        # Boucle infinie → timeout 20s ; on raccourcit via monkeypatch.
        import boss_agent
        orig = boss_agent.subprocess.run
        def fake_run(*a, **k):
            raise boss_agent.subprocess.TimeoutExpired(cmd=a[0] if a else "py", timeout=1)
        boss_agent.subprocess.run = fake_run
        try:
            errs = d.smoke_test(Deliverable(kind="python", content="while True: pass"), "dev")
            assert errs and "dépasse" in errs[0]
        finally:
            boss_agent.subprocess.run = orig

    def test_coupe_circuit_souvre(self, tmp_path):
        d = self._make(tmp_path)
        for _ in range(3):
            d.record("dev", False)
        assert d.is_open("dev") is True

    def test_coupe_circuit_reset_apres_succes(self, tmp_path):
        d = self._make(tmp_path)
        d.record("dev", False)
        d.record("dev", False)
        d.record("dev", True)  # reset
        assert d.is_open("dev") is False

    def test_incident_journalise(self, tmp_path):
        d = self._make(tmp_path)
        t = Task(id="t1", title="x", role="dev", instructions="")
        d.incident(t, "format", "JSON cassé")
        assert len(d.incidents) == 1
        assert d.incidents[0]["task"] == "t1"


# --------------------------------------------------------------------------- #
#  6. Boss.plan — mock LLM, routage rôle inconnu → generaliste
# --------------------------------------------------------------------------- #
class TestBossPlan:
    def test_plan_routage_role_inconnu(self, tmp_runs):
        # Le planner renvoie une tâche avec un rôle qui n'existe pas.
        plan_json = {"tasks": [
            {"id": "t1", "title": "Faire X", "role": "magicien",
             "instructions": "...", "kind": "text", "acceptance": [],
             "depends_on": []},
        ]}
        tmp_runs.llm._json_map = {"Mission": json.dumps(plan_json)}
        tasks = tmp_runs.plan("test")
        assert len(tasks) == 1
        assert tasks[0].role == "generaliste"  # repli automatique

    def test_plan_plusieurs_taches_avec_dependances(self, tmp_runs):
        plan_json = {"tasks": [
            {"id": "t1", "title": "Recherche", "role": "analyste",
             "instructions": "...", "kind": "text", "acceptance": [], "depends_on": []},
            {"id": "t2", "title": "Rédaction", "role": "redacteur",
             "instructions": "...", "kind": "text", "acceptance": [],
             "depends_on": ["t1"]},
        ]}
        tmp_runs.llm._json_map = {"Mission": json.dumps(plan_json)}
        tasks = tmp_runs.plan("mission")
        assert {t.id for t in tasks} == {"t1", "t2"}
        assert tasks[1].depends_on == ["t1"]


# --------------------------------------------------------------------------- #
#  7. Boss.run — orchestration complète (LLM mocké)
# --------------------------------------------------------------------------- #
class TestBossRun:
    def test_run_complet_une_tache_texte(self, tmp_path):
        plan = {"tasks": [{"id": "t1", "title": "Dire bonjour", "role": "redacteur",
                           "instructions": "Dis bonjour", "kind": "text",
                           "acceptance": [], "depends_on": []}]}
        llm = FakeLLM(
            json_map={"Mission": json.dumps(plan)},
            default_text="Bonjour le monde",
        )
        boss = Boss(approver=lambda *a: True, base_dir=str(tmp_path), llm=llm)
        report = boss.run("mission test")
        assert report["statut"] == "complet"
        assert report["taches"]["t1"]["statut"] == "done"
        assert report["a_traiter_par_humain"] == []
        assert len(report["livrables"]) == 1

    def test_run_code_python_smoke_test_reussit(self, tmp_path):
        plan = {"tasks": [{"id": "t1", "title": "Script", "role": "developpeur",
                           "instructions": "Calcule 1+1", "kind": "python",
                           "acceptance": [], "depends_on": []}]}
        llm = FakeLLM(
            json_map={"Mission": json.dumps(plan)},
            text_map={"Calcule 1+1": "print(1+1)"},  # code valide qui s'exécute
        )
        boss = Boss(approver=lambda *a: True, base_dir=str(tmp_path), llm=llm)
        report = boss.run("mission")
        assert report["statut"] == "complet"
        assert report["taches"]["t1"]["statut"] == "done"

    def test_run_code_python_syntaxe_erreur_escalade(self, tmp_path):
        plan = {"tasks": [{"id": "t1", "title": "Script", "role": "developpeur",
                           "instructions": "Code", "kind": "python",
                           "acceptance": [], "depends_on": []}]}
        llm = FakeLLM(
            json_map={"Mission": json.dumps(plan)},
            default_text="def(",  # syntaxe invalide → toujours échoue
        )
        boss = Boss(approver=lambda *a: True, base_dir=str(tmp_path), llm=llm)
        report = boss.run("mission")
        assert report["statut"] == "partiel"
        assert report["taches"]["t1"]["statut"] == "escalated"
        assert "t1" in report["a_traiter_par_humain"]
        assert len(report["incidents"]) > 0  # le docteur est intervenu

    def test_run_health_check_llm_injoignable(self, tmp_path, monkeypatch):
        # Raccourcit le cooldown pour ne pas attendre 60 s en boucle.
        import boss_agent
        monkeypatch.setattr(boss_agent, "PROVIDER_COOLDOWN", 1)
        llm = FakeLLM(ping_ok=False)
        boss = Boss(approver=lambda *a: True, base_dir=str(tmp_path), llm=llm)
        report = boss.run("mission")
        assert "erreur" in report
        assert "injoignables" in report["erreur"]

    def test_run_dependance_echec_bloque_suite(self, tmp_path):
        plan = {"tasks": [
            {"id": "t1", "title": "Code cassé", "role": "developpeur",
             "instructions": "Code", "kind": "python", "acceptance": [], "depends_on": []},
            {"id": "t2", "title": "Doc", "role": "redacteur",
             "instructions": "Doc", "kind": "text", "acceptance": [],
             "depends_on": ["t1"]},
        ]}
        llm = FakeLLM(
            json_map={"Mission": json.dumps(plan)},
            default_text="def(",  # code invalide → t1 échoue
        )
        boss = Boss(approver=lambda *a: True, base_dir=str(tmp_path), llm=llm)
        report = boss.run("mission")
        # t1 échoue → t2 bloquée → les deux escaladées
        assert report["taches"]["t1"]["statut"] == "escalated"
        assert report["taches"]["t2"]["statut"] == "escalated"


# --------------------------------------------------------------------------- #
#  8. CallableWorker — branchement d'un agent externe
# --------------------------------------------------------------------------- #
class TestCallableWorker:
    def test_execute_appelle_la_fonction(self):
        def fn(task):
            return Deliverable(kind="file", path="/tmp/x", content="")
        w = CallableWorker("externe", fn)
        d = w.execute(MagicMock(), {}, [], None)
        assert d.kind == "file"

    def test_dans_le_boss_pas_de_fallback_generaliste(self, tmp_path):
        # Un CallableWorker qui échoue toujours ne doit PAS basculer vers
        # le généraliste (ce dernier ne sait pas produire le même livrable).
        plan = {"tasks": [{"id": "t1", "title": "Pub", "role": "agent_pub",
                           "instructions": "Fais un post", "kind": "file",
                           "acceptance": [], "depends_on": []}]}
        llm = FakeLLM(json_map={"Mission": json.dumps(plan)})

        def fn_qu_echoue(task):
            raise RuntimeError("panne agent externe")

        boss = Boss(approver=lambda *a: True, base_dir=str(tmp_path), llm=llm)
        boss.register(CallableWorker("agent_pub", fn_qu_echoue),
                      {Scope.READ, Scope.WRITE})
        report = boss.run("mission")
        assert report["taches"]["t1"]["statut"] == "escalated"


# --------------------------------------------------------------------------- #
#  9. Rapport & checkpoint (fichiers produits)
# --------------------------------------------------------------------------- #
class TestRapport:
    def test_rapport_json_ecrit_sur_disque(self, tmp_path):
        plan = {"tasks": [{"id": "t1", "title": "Txt", "role": "redacteur",
                           "instructions": "x", "kind": "text",
                           "acceptance": [], "depends_on": []}]}
        llm = FakeLLM(json_map={"Mission": json.dumps(plan)},
                      default_text="livrable")
        boss = Boss(approver=lambda *a: True, base_dir=str(tmp_path), llm=llm)
        boss.run("mission")
        rapport = boss.run_dir / "rapport.json"
        assert rapport.exists()
        data = json.loads(rapport.read_text(encoding="utf-8"))
        assert data["statut"] == "complet"

    def test_state_json_checkpoint(self, tmp_path):
        plan = {"tasks": [{"id": "t1", "title": "Txt", "role": "redacteur",
                           "instructions": "x", "kind": "text",
                           "acceptance": [], "depends_on": []}]}
        llm = FakeLLM(json_map={"Mission": json.dumps(plan)},
                      default_text="ok")
        boss = Boss(approver=lambda *a: True, base_dir=str(tmp_path), llm=llm)
        boss.run("mission")
        state = boss.run_dir / "state.json"
        assert state.exists()
        taches = json.loads(state.read_text(encoding="utf-8"))
        assert taches[0]["status"] == "done"


# --------------------------------------------------------------------------- #
#  Mode autonome (sans pytest) : python test_boss.py
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    # Si pytest n'est pas installé, on exécute les tests à la main.
    import tempfile, traceback

    class FakeTmp:
        def __init__(self, p): self._p = p
        def __truediv__(self, o): return self._p / o

    passed, failed = 0, 0
    # ... (exécution simplifiée — pytest est préférable)
    print("Lance plutôt : python -m pytest test_boss.py -v")
    print("(pytest détectera automatiquement toutes les classes Test*)")
