# Guide de lancement — Browser Skill industriel (4 prompts séquentiels)

## Prérequis

- **Claude Code** installé et configuré (`claude` en ligne de commande), ou **Codex CLI**
- Un répertoire de travail vide pour le projet
- Le fichier `browser_skill_prompts_v2.md` accessible (généré à l'étape précédente)

## Méthode recommandée : Claude Code en mode interactif

Claude Code conserve le contexte entre les messages d'une même session. C'est la méthode la plus fiable pour chaîner les 4 prompts.

### Étape 0 — Préparer le répertoire

```bash
mkdir -p ~/projects/browser-use && cd ~/projects/browser-use
git init
```

### Étape 1 — Lancer Claude Code

```bash
claude
```

Tu es maintenant dans la session interactive. Les 4 prompts suivants sont à coller **un par un, dans l'ordre**, en attendant que la génération soit terminée avant de passer au suivant.

### Étape 2 — Prompt 1 (code applicatif core)

Copie-colle **l'intégralité du contenu** du bloc `Prompt 1 — Code applicatif core` depuis le fichier `browser_skill_prompts_v2.md` (tout le texte entre les balises ```` ````text ```` et ```` ```````` ````).

Attends que Claude ait fini de générer tous les fichiers. Vérifie :

```bash
# Dans un autre terminal
ls app/
# Tu dois voir : __init__.py config.py models.py security.py fetcher.py parser.py
#                auth_detector.py pdf_handler.py image_handler.py llm_client.py
#                browser_fallback.py markdown_builder.py orchestrator.py utils.py
```

### Étape 3 — Prompt 2 (API, OpenWebUI, Docker multi-arch)

Copie-colle le bloc `Prompt 2`. Attends la fin. Vérifie :

```bash
ls app/main.py app/api.py app/openwebui_tool.py
ls docker/Dockerfile docker/Dockerfile.browser
ls scripts/build_multiarch.sh
cat requirements.txt
```

### Étape 4 — Prompt 3 (tests fonctionnels et sécurité)

Copie-colle le bloc `Prompt 3`. Attends la fin. Vérifie :

```bash
ls tests/security/ tests/functional/ tests/integration/
ls tests/conftest.py
cat datasets/urls.txt
```

### Étape 5 — Prompt 4 (K8s, load tests, README)

Copie-colle le bloc `Prompt 4`. Attends la fin. Vérifie :

```bash
ls k8s/
ls tests/load/locustfile.py
cat README.md | head -30
```

### Étape 6 — Validation rapide

```bash
# Installer les dépendances
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt

# Vérifier que l'app démarre
cp .env.example .env
# Éditer .env avec une vraie clé SCW si disponible, sinon laisser FEATURES_ENABLED=extraction
uvicorn app.main:app --port 8000 &
curl -s http://localhost:8000/healthz | python -m json.tool
kill %1

# Lancer les tests (hors intégration)
pytest tests/security/ tests/functional/ -v

# Build Docker (single arch, local)
docker build -f docker/Dockerfile -t browser-use:local .
docker run --rm -p 8000:8000 --env-file .env browser-use:local &
curl -s http://localhost:8000/healthz
docker stop $(docker ps -q --filter ancestor=browser-use:local)

# Build multi-arch (nécessite buildx configuré)
# docker buildx create --use --name multiarch --driver docker-container
# REGISTRY=ghcr.io/ton-org TAG=dev bash scripts/build_multiarch.sh
```

## Méthode alternative : Claude Code en one-shot par prompt

Si tu préfères lancer chaque prompt séparément (sessions distinctes), ajoute un préambule de contexte à chaque prompt après le premier :

```text
I am continuing a project. The following files already exist in the current directory and must NOT be regenerated:

[colle ici la sortie de: find . -name "*.py" -o -name "*.yaml" -o -name "*.txt" -o -name "Dockerfile*" | sort]

Import from these existing modules. Do not rewrite them.
```

Puis colle le prompt correspondant.

## Méthode alternative : Codex CLI

```bash
# Prompt 1
codex --model claude-opus-4-20250514 --full-auto "$(cat prompt1.txt)"

# Attendre, puis prompt 2
codex --model claude-opus-4-20250514 --full-auto "$(cat prompt2.txt)"

# etc.
```

Pour cette méthode, extrais chaque bloc prompt dans un fichier séparé (`prompt1.txt`, `prompt2.txt`, etc.).

## Dépannage

| Problème | Solution |
|----------|----------|
| Claude s'arrête au milieu d'un fichier | Tape `continue` ou `continue generating the remaining files` |
| Un module importe un fichier pas encore généré | Normal si tu n'es pas dans l'ordre. Respecter la séquence 1→2→3→4 |
| `pymupdf` ne s'installe pas sur arm64 | Vérifier que tu as `pip >= 23.0` et Python 3.11+. pymupdf publie des wheels arm64 depuis la v1.23 |
| `docker buildx` échoue | Créer le builder : `docker buildx create --use --name multiarch --driver docker-container` |
| Les tests d'intégration échouent (réseau) | Normal en environnement isolé. Lancer uniquement : `pytest tests/security/ tests/functional/ -v` |
| Playwright ne s'installe pas dans le conteneur | Utiliser `docker/Dockerfile.browser` (image Microsoft), pas `docker/Dockerfile` |
| Le healthcheck renvoie 503 | Vérifier le `.env` — les variables requises par `FEATURES_ENABLED` doivent être présentes |

## Après la génération : checklist de revue

Une fois les 4 prompts exécutés, passe en revue ces points critiques avant de considérer le code comme utilisable :

- [ ] `app/security.py` — vérifier que la résolution DNS pré-connexion est implémentée (pas juste un TODO)
- [ ] `app/config.py` — vérifier que `FEATURES_ENABLED` contrôle bien le fail-fast au startup
- [ ] `docker/Dockerfile` — vérifier que le `USER appuser` est bien après le `COPY` et avant le `CMD`
- [ ] `k8s/deployment.yaml` — vérifier que les noms de secrets/configmaps matchent entre les fichiers
- [ ] `k8s/networkpolicy.yaml` — vérifier que le label du namespace ingress-nginx est correct pour ton cluster
- [ ] `tests/conftest.py` — vérifier que les fixtures synthétiques génèrent bien un vrai PDF avec pymupdf
- [ ] `app/openwebui_tool.py` — tester le copier-coller dans OpenWebUI → Tools → Create Tool
- [ ] Les `requirements.txt` — faire un `pip-audit` pour vérifier l'absence de CVE connues
- [ ] Lancer `bandit -r app/ -ll` et traiter les findings medium+
