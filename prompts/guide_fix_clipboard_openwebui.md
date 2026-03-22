# Fix du copier-coller OpenWebUI — Guide technique et déploiement

## Problème

Le bouton **Copy** d'OpenWebUI (toutes versions ≤ 0.8.10) copie le **markdown brut** dans le presse-papier. Quand l'utilisateur colle dans Word, Outlook, un mail ou tout éditeur riche, il obtient des `#`, `**`, `|---|` au lieu d'un texte formaté.

**Exemple** — ce que l'utilisateur obtient en collant :

```
### Titre
**Gras** et *italique*
| Col1 | Col2 |
|------|------|
| val  | val  |
```

Au lieu de :

> **Titre**
> **Gras** et *italique*
> avec un vrai tableau formaté

## Cause racine

OpenWebUI utilise `navigator.clipboard.writeText(markdownSource)` pour le bouton Copy. Cette API n'écrit que `text/plain` — pas de `text/html`. L'application de destination ne reçoit donc que le markdown brut.

## Solution

Patcher `Clipboard.prototype.writeText` pour intercepter tous les appels et écrire **deux formats simultanément** via `navigator.clipboard.write([ClipboardItem])` :

| Format | Contenu | Utilisé par |
|--------|---------|-------------|
| `text/plain` | Texte propre avec retours à la ligne, tableaux en colonnes tabulées, listes numérotées | Notepad, Terminal, VS Code |
| `text/html` | HTML rendu tel qu'affiché dans OpenWebUI | Word, Outlook, Google Docs, mail |

### Obstacles techniques rencontrés

1. **`loader.js` ne s'exécute pas** — OpenWebUI charge ce fichier avec `<script defer crossorigin="use-credentials">`. Sans header CORS `Access-Control-Allow-Credentials`, le navigateur charge le fichier mais refuse silencieusement de l'exécuter.

2. **Patch sur `navigator.clipboard.writeText`** — Ne fonctionne pas car les composants Svelte d'OpenWebUI capturent la référence à la fonction originale au moment de l'import, avant que le patch ne s'applique.

3. **Patch sur `Clipboard.prototype.writeText`** — ✅ Fonctionne. Le prototype est partagé, donc même si Svelte a une référence `this.clipboard.writeText`, l'appel passe par le prototype patché.

4. **Sélecteur CSS `.prose`** — 0 résultats. OpenWebUI v0.8.x utilise la classe `.markdown-prose` pour les blocs de contenu rendu. Corrigé en `.markdown-prose, .prose` pour compatibilité multi-versions.

5. **`innerText` sur un clone détaché** — Ne préserve pas les retours à la ligne car le clone n'a pas de layout CSS. Corrigé avec une fonction `htmlToPlainText()` qui parcourt le DOM et reconstruit le texte avec la bonne structure.

### Conversion text/plain

La fonction `htmlToPlainText()` gère :

- **Tableaux** → colonnes séparées par des tabulations (`\t`), compatible Excel/Sheets
- **Listes à puces** → préfixe `• ` avec indentation
- **Listes numérotées** → préfixe `1. `, `2. `, etc.
- **Headings** → saut de ligne avant/après
- **Paragraphes** → saut de ligne avant/après
- **Code blocks** → préservés tels quels
- **`<br>` / `<hr>`** → convertis en `\n` / `---`
- **Nettoyage** → collapse des sauts de ligne multiples, trim par ligne

## Fichiers

```
browser-skill-owui/
├── scripts/
│   ├── fix_openwebui_clipboard.js    ← le patch JS (source de vérité)
│   └── diag_openwebui_clipboard.js   ← outil de diagnostic console navigateur
└── prompts/
    └── guide_fix_clipboard_openwebui.md  ← ce fichier

grafrag-experimentation/
├── openwebui/custom/
│   ├── index.html   ← index.html patchée avec le script inline
│   └── custom.css   ← placeholder pour CSS custom
└── docker-compose.yml  ← volume mount de index.html
```

## Déploiement local (Docker Compose)

### Méthode

Le script est injecté **inline dans `index.html`** via un volume Docker :

```yaml
# docker-compose.yml — service openwebui
volumes:
  - ./openwebui/data:/app/backend/data
  - ./openwebui/custom/index.html:/app/build/index.html:ro
  - ./openwebui/custom/custom.css:/app/backend/open_webui/static/custom.css:ro
```

### Étapes

1. Récupérer l'`index.html` original du container :
   ```bash
   docker cp <container>:/app/build/index.html openwebui/custom/index.html
   ```

2. Injecter le script avant `</head>` :
   ```bash
   python3 -c "
   import pathlib
   index = pathlib.Path('openwebui/custom/index.html').read_text()
   patch = '<script>\n' + pathlib.Path('../browser-skill-owui/scripts/fix_openwebui_clipboard.js').read_text() + '\n</script>'
   patched = index.replace('</head>', patch + '\n</head>')
   pathlib.Path('openwebui/custom/index.html').write_text(patched)
   "
   ```

3. Redémarrer OpenWebUI :
   ```bash
   docker compose restart openwebui
   ```

### Attention lors d'une mise à jour OpenWebUI

Si l'image OpenWebUI est mise à jour (ex: v0.8.10 → v0.9.0), l'`index.html` original change. Il faut :

1. Extraire le nouvel `index.html` de la nouvelle image
2. Ré-injecter le script
3. Recréer le volume mount

Script d'automatisation :
```bash
IMAGE="ghcr.io/open-webui/open-webui:v0.9.0"
docker run --rm "${IMAGE}" cat /app/build/index.html > /tmp/new_index.html
python3 -c "
import pathlib
idx = pathlib.Path('/tmp/new_index.html').read_text()
fix = pathlib.Path('scripts/fix_openwebui_clipboard.js').read_text()
out = idx.replace('</head>', '<script>\n' + fix + '\n</script>\n</head>')
pathlib.Path('openwebui/custom/index.html').write_text(out)
"
docker compose restart openwebui
```

## Déploiement Kubernetes (grande échelle)

### Méthode recommandée : InitContainer + ConfigMap

Pour un cluster K8s, la méthode la plus robuste est :

1. **ConfigMap** contenant le script JS
2. **InitContainer** qui copie l'`index.html` original, injecte le script, et le place dans un volume partagé
3. Le container OpenWebUI principal monte ce volume

### Manifests

#### ConfigMap avec le script

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: openwebui-clipboard-fix
  namespace: grafrag
data:
  fix_clipboard.js: |
    # Coller ici le contenu de scripts/fix_openwebui_clipboard.js
```

#### Deployment avec InitContainer

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openwebui
  namespace: grafrag
spec:
  template:
    spec:
      initContainers:
        - name: patch-index-html
          image: ${OPENWEBUI_IMAGE}
          command:
            - sh
            - -c
            - |
              cp /app/build/index.html /patched/index.html
              # Inject the script before </head>
              SCRIPT=$(cat /fix/fix_clipboard.js)
              sed -i "s|</head>|<script>\n${SCRIPT}\n</script>\n</head>|" /patched/index.html
              echo "Patched index.html with clipboard fix"
          volumeMounts:
            - name: patched-html
              mountPath: /patched
            - name: clipboard-fix
              mountPath: /fix

      containers:
        - name: openwebui
          image: ${OPENWEBUI_IMAGE}
          volumeMounts:
            - name: patched-html
              mountPath: /app/build/index.html
              subPath: index.html
              readOnly: true
            # ... autres volumes (data, etc.)

      volumes:
        - name: patched-html
          emptyDir: {}
        - name: clipboard-fix
          configMap:
            name: openwebui-clipboard-fix
```

### Avantages de cette approche

- **Indépendant de la version** : l'InitContainer utilise la même image que le container principal, donc l'`index.html` correspond toujours
- **Pas de rebuild d'image** : le patch est un ConfigMap, modifiable sans rebuilder
- **Rollback facile** : supprimer le ConfigMap et l'InitContainer pour revenir au comportement original
- **GitOps compatible** : le ConfigMap est versionné dans le repo, déployable via ArgoCD/Flux

### Alternative : image custom

Si l'organisation préfère une image Docker patchée :

```dockerfile
FROM ghcr.io/open-webui/open-webui:v0.8.10

COPY fix_openwebui_clipboard.js /tmp/fix.js
RUN sed -i 's|</head>|<script>\n'"$(cat /tmp/fix.js)"'\n</script>\n</head>|' /app/build/index.html \
    && rm /tmp/fix.js
```

Inconvénient : il faut rebuilder à chaque mise à jour d'OpenWebUI.

## Diagnostic sur une instance distante

Pour diagnostiquer le problème sur une instance à laquelle on n'a pas accès SSH (ex: `chat.interieur.gouv.fr`) :

1. Ouvrir la console navigateur (F12)
2. Coller le contenu de `scripts/diag_openwebui_clipboard.js`
3. Suivre les instructions affichées dans la console
4. Le rapport indique la version, les assets custom, et si le clipboard contient du markdown

## Compatibilité

| Version OpenWebUI | Sélecteur CSS | Status |
|-------------------|---------------|--------|
| 0.6.x — 0.7.x | `.prose` | Non testé, devrait fonctionner |
| 0.8.x — 0.8.10 | `.markdown-prose` | ✅ Testé et validé |
| 0.9.x+ | `.markdown-prose` ou `.prose` | Le script utilise les deux sélecteurs |

Le script est rétro-compatible : il cherche `.markdown-prose, .prose` et utilise le premier match.
