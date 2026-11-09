# -*- coding: utf-8 -*-
"""Ajoute des topics/tags au dépôt GitHub via l'API REST.

Utilise le token en cache dans Windows Credential Manager (git credential fill).
Aucune interaction humaine. À relancer si on veut ajouter des tags.

Usage : python _set_topics.py
"""
import json, re, subprocess, urllib.request

# Récupérer le token GitHub en cache.
inp = b"protocol=https\nhost=github.com\n\n"
out = subprocess.run(["git", "credential", "fill"], input=inp,
                     capture_output=True).stdout.decode()
token = re.search(r"^password=(.*)$", out, re.MULTILINE).group(1)
user = "haouchinelotfi-ui"
repo = "boss-agent"

TOPICS = ["ai-agent", "automation", "autonomous-agents", "llm", "local-first",
          "multi-agent", "python", "streamlit", "telegram-bot",
          "task-orchestration", "free", "no-api-key"]

# /repos/{owner}/{repo}/topics accepte un média spécifique pour PUT/GET JSON.
url = f"https://api.github.com/repos/{user}/{repo}/topics"
data = json.dumps({"names": TOPICS}).encode()
req = urllib.request.Request(url, data=data, method="PUT")
req.add_header("Authorization", f"token {token}")
req.add_header("Accept", "application/vnd.github.mercy-preview+json")
req.add_header("Content-Type", "application/json")

resp = urllib.request.urlopen(req)
result = json.loads(resp.read().decode())
print("Topics OK :", result.get("names", TOPICS))
