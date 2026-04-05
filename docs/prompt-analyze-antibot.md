# Prompt Claude Desktop — Analyse anti-bot liberation.fr

Copie-colle ce prompt dans Claude Desktop. Avant de lancer, ouvre liberation.fr dans Chrome et exporte un fichier HAR depuis les DevTools (Network > clic droit > Save all as HAR with content).

---

## Prompt

```
Je développe un outil de capture de pages web (Playwright headless + Chromium) qui est bloqué par l'anti-bot de liberation.fr (Datadome). J'ai besoin que tu analyses ce qui se passe quand un vrai navigateur se connecte vs ce que fait Playwright, pour trouver les différences exploitables.

### Contexte technique

Mon outil actuel fait :
- Playwright Chromium headless
- User-Agent Chrome 131
- Stealth JS : masque navigator.webdriver, simule chrome.runtime, plugins, permissions
- --disable-blink-features=AutomationControlled
- Challenge retry : attend 4s + reload si body < 200 chars (2 retries max)

Résultat : le site retourne un body vide (0 chars), titre "liberation.fr", pas de contenu. Le challenge Datadome ne se résout jamais.

### Ce que je te demande

1. **Ouvre https://www.liberation.fr dans ton navigateur** et capture :
   - Les requêtes réseau (surtout celles vers datadome, geo.captcha-delivery, ou tout domaine tiers lié à la protection)
   - Les cookies posés (notamment ceux commençant par `datadome`, `dd_`, ou `__dd`)
   - Les headers de la requête initiale et de la réponse
   - Tout script JS chargé depuis un domaine externe (datadome, captcha-delivery, etc.)

2. **Analyse les différences** entre ce qu'un vrai Chrome fait et ce que Playwright headless fait :
   - Quels endpoints Datadome appelle-t-il ?
   - Quel cookie ou token est nécessaire pour passer ?
   - Y a-t-il un challenge CAPTCHA invisible ou juste un fingerprint JS ?
   - Le challenge est-il résolu côté client (JS compute) ou côté serveur (validation de cookie) ?

3. **Propose des solutions concrètes** classées par difficulté :
   - Niveau 1 : ajustements Playwright (headers, cookies, timing)
   - Niveau 2 : pré-résolution du challenge (extraire le JS Datadome, le résoudre, injecter le cookie)
   - Niveau 3 : contournement architectural (proxy, service tiers, headed mode)

4. **Si tu as accès au fichier HAR** que je joins, analyse-le pour extraire :
   - L'ordre exact des requêtes
   - Le cookie Datadome et comment il est généré
   - Les headers spécifiques que Datadome vérifie
   - Le payload du challenge JS (s'il est visible dans le HAR)

### Format de réponse attendu

Donne-moi :
- Un **diagnostic** : quel type de protection Datadome utilise sur ce site (device check, JS challenge, CAPTCHA invisible, etc.)
- Une **trace** : le flux réseau simplifié (requête → réponse → cookie → redirect → contenu)
- Des **patches concrets** : snippets Python/Playwright que je peux intégrer dans mon browser_fallback.py
- Une **évaluation** : quelle solution a le meilleur ratio effort/fiabilité

Mon fichier browser_fallback.py utilise Playwright async avec :
- async_playwright() → chromium.launch(headless=True, args=[...])
- context.add_init_script(stealth_js)
- page.goto(url, wait_until="networkidle")
- Retry si body < 200 chars
```

---

## Variante avec HAR joint

Si tu as exporté le HAR, ajoute avant le prompt :

```
Je joins le fichier HAR d'une session réelle Chrome sur liberation.fr.
Analyse-le en détail avant de répondre.
```

Puis glisse le fichier .har dans la conversation Claude Desktop.

## Comment exporter le HAR

1. Ouvre Chrome → F12 (DevTools) → onglet **Network**
2. Coche **Preserve log**
3. Va sur https://www.liberation.fr
4. Attends que la page charge complètement
5. Clic droit dans la liste des requêtes → **Save all as HAR with content**
6. Le fichier fait ~2-5 MB, Claude Desktop le digère sans problème
