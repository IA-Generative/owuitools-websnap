/**
 * Diagnostic OpenWebUI — Copier-coller markdown
 *
 * Usage : ouvrir la console du navigateur (F12) sur chat.interieur.gouv.fr
 *         et coller tout ce script. Il affichera un rapport diagnostic.
 *
 * Ensuite : copier un message via le bouton Copy d'OpenWebUI,
 *           puis appeler : diagClipboard()
 */

(async function diagOpenWebUI() {
  const report = {};

  // 1. Version OpenWebUI
  try {
    const r = await fetch('/api/version');
    const d = await r.json();
    report.version = d.version;
  } catch (e) {
    report.version = 'inaccessible (' + e.message + ')';
  }

  // 2. Config publique
  try {
    const r = await fetch('/api/config');
    const d = await r.json();
    report.name = d.name;
    report.features = d.features;
    report.default_models = d.default_models;
  } catch (e) {
    report.config = 'inaccessible';
  }

  // 3. Custom CSS/JS chargés
  const customAssets = [];
  document.querySelectorAll('link[rel="stylesheet"], script[src]').forEach(el => {
    const src = el.href || el.src || '';
    if (src.includes('custom') || src.includes('loader') || src.includes('override')) {
      customAssets.push(src);
    }
  });
  report.customAssets = customAssets.length ? customAssets : 'aucun';

  // 4. Content-Security-Policy
  report.csp = document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.content || 'non défini en meta';

  // 5. Boutons Copy — vérifier le mécanisme
  const copyButtons = document.querySelectorAll('button[aria-label*="Copy"], button[title*="Copy"], button[aria-label*="Copier"]');
  report.copyButtonsFound = copyButtons.length;

  // 6. Service Worker ou extensions qui interceptent le clipboard
  if (navigator.serviceWorker?.controller) {
    report.serviceWorker = navigator.serviceWorker.controller.scriptURL;
  } else {
    report.serviceWorker = 'aucun';
  }

  // 7. User-Agent
  report.userAgent = navigator.userAgent;

  // 8. Reverse proxy headers (via a simple HEAD request)
  try {
    const r = await fetch('/', { method: 'HEAD' });
    const interestingHeaders = {};
    for (const [k, v] of r.headers.entries()) {
      if (['server', 'x-powered-by', 'x-frame-options', 'content-security-policy',
           'x-proxy', 'via', 'x-forwarded-for', 'x-real-ip'].includes(k.toLowerCase())) {
        interestingHeaders[k] = v;
      }
    }
    report.proxyHeaders = Object.keys(interestingHeaders).length ? interestingHeaders : 'aucun header proxy détecté';
  } catch (e) {
    report.proxyHeaders = 'erreur: ' + e.message;
  }

  // Affichage
  console.log('%c=== Diagnostic OpenWebUI — Clipboard ===', 'color: #2196F3; font-size: 16px; font-weight: bold;');
  console.table(report);
  console.log('%cRapport complet :', 'font-weight: bold;');
  console.log(JSON.stringify(report, null, 2));

  console.log('%c\n=== Étape suivante ===' , 'color: #FF9800; font-size: 14px; font-weight: bold;');
  console.log('1. Copie un message via le bouton "Copy" d\'OpenWebUI');
  console.log('2. Puis tape dans la console :  diagClipboard()');
  console.log('3. Ça affichera ce que le clipboard contient (markdown brut vs texte)');

  // Expose helper — méthode 1 : via clipboard API (nécessite focus sur la page)
  // Méthode 2 (plus fiable) : intercepte le prochain Ctrl+V / Cmd+V dans un champ invisible
  window.diagClipboard = function() {
    console.log('%c=== Diagnostic clipboard ===', 'color: #4CAF50; font-size: 14px; font-weight: bold;');
    console.log('1. Copie un message via le bouton Copy d\'OpenWebUI');
    console.log('2. Clique n\'importe où sur la PAGE (pas la console)');
    console.log('3. Puis appuie Ctrl+V (ou Cmd+V) sur la page');
    console.log('→ Le résultat s\'affichera ici automatiquement.\n');

    // Create invisible textarea to capture paste
    const trap = document.createElement('textarea');
    trap.style.cssText = 'position:fixed;top:0;left:0;opacity:0.01;width:1px;height:1px;z-index:999999;';
    document.body.appendChild(trap);
    trap.focus();

    trap.addEventListener('paste', (e) => {
      e.preventDefault();
      const text = e.clipboardData.getData('text/plain');
      const html = e.clipboardData.getData('text/html');

      const isMarkdown = /[#*`\[\]|>-]{2,}/.test(text) || /^#{1,6}\s/m.test(text) || /\*\*[^*]+\*\*/.test(text);

      console.log('%c=== Contenu collé (text/plain) ===', 'color: #4CAF50; font-size: 14px; font-weight: bold;');
      console.log(text.substring(0, 1000) + (text.length > 1000 ? '\n...(tronqué)' : ''));

      if (html) {
        console.log('%c\n=== Contenu collé (text/html) ===', 'color: #2196F3; font-size: 14px; font-weight: bold;');
        console.log(html.substring(0, 500) + (html.length > 500 ? '\n...(tronqué)' : ''));
      } else {
        console.log('\n⚠️ Pas de text/html dans le clipboard — seul le texte brut est copié.');
      }

      console.log('%c\nAnalyse :', 'font-weight: bold;');
      console.log('Longueur texte :', text.length, 'caractères');
      console.log('HTML présent :', html ? 'oui (' + html.length + ' chars)' : 'non');
      console.log('Contient du markdown :', isMarkdown ? '⚠️ OUI' : '✅ NON');

      if (isMarkdown && !html) {
        console.log('%c\n→ DIAGNOSTIC : le bouton Copy copie le markdown brut sans HTML.', 'color: red; font-weight: bold;');
        console.log('C\'est le comportement par défaut d\'OpenWebUI.');
        console.log('Tape :  showFix()  pour voir le patch correctif.');
      } else if (isMarkdown && html) {
        console.log('%c\n→ DIAGNOSTIC : markdown ET html présents.', 'color: orange; font-weight: bold;');
        console.log('L\'app de destination choisit le format text/plain au lieu de text/html.');
        console.log('Solution : coller avec Ctrl+Shift+V (collage sans format) ou utiliser le patch.');
      } else {
        console.log('%c\n→ Le clipboard contient du texte normal, pas de markdown.', 'color: green;');
      }

      // Cleanup
      document.body.removeChild(trap);
    });

    // Also try direct clipboard API after a click
    document.addEventListener('click', async function onceClick() {
      document.removeEventListener('click', onceClick);
      try {
        const text = await navigator.clipboard.readText();
        // Don't duplicate if paste trap already handled it
        if (trap.parentNode) {
          const isMarkdown = /[#*`\[\]|>-]{2,}/.test(text) || /^#{1,6}\s/m.test(text) || /\*\*[^*]+\*\*/.test(text);
          console.log('%c=== Clipboard lu directement ===', 'color: #4CAF50; font-size: 14px;');
          console.log(text.substring(0, 500));
          console.log('Markdown :', isMarkdown ? '⚠️ OUI' : '✅ NON');
          document.body.removeChild(trap);
        }
      } catch(e) { /* ignore, paste trap handles it */ }
    }, { once: true });
  };

  window.showFix = function() {
    console.log('%c=== Patch copier-coller ===', 'color: #9C27B0; font-size: 14px; font-weight: bold;');
    console.log('À ajouter dans Admin Panel → Settings → Interface → Custom JS :');
    console.log(`
// Override OpenWebUI copy buttons to copy plain text instead of markdown
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('button[aria-label*="Copy"], button[aria-label*="Copier"]');
  if (!btn) return;

  // Find the message container (sibling or parent)
  const msgContainer = btn.closest('.message, [data-message-id], .prose');
  if (!msgContainer) return;

  // Get rendered text (not markdown source)
  const renderedText = msgContainer.innerText || msgContainer.textContent;

  // Prevent default copy and write plain text
  e.preventDefault();
  e.stopPropagation();

  try {
    await navigator.clipboard.writeText(renderedText.trim());
    // Visual feedback
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '✓';
    setTimeout(() => { btn.innerHTML = originalHTML; }, 1500);
  } catch (err) {
    console.error('Copy failed:', err);
  }
}, true);
`);
  };

})();
