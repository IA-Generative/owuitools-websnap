// Fix OpenWebUI copy button: write both text/plain AND text/html to clipboard.
//
// Deploy: mount or copy as /app/backend/open_webui/static/loader.js
//
// Behaviour:
//   - Word, Outlook, Google Docs → paste formatted content (text/html)
//   - Notepad, Terminal, VS Code → paste clean text (text/plain)
//   - Original markdown is NOT in the clipboard (that was the bug)

(function () {
  "use strict";

  document.addEventListener(
    "click",
    async (e) => {
      const btn = e.target.closest(
        'button[aria-label*="Copy"], button[aria-label*="Copier"], button[data-clipboard]'
      );
      if (!btn) return;

      // Find the rendered message content
      const prose =
        btn.closest(".prose") ||
        btn.closest(".message") ||
        btn.closest("[data-message-id]");
      if (!prose) return;

      // Clone to avoid modifying the visible DOM
      const clone = prose.cloneNode(true);

      // Remove copy buttons and action bars from the clone
      clone
        .querySelectorAll("button, .code-block-header, .message-actions")
        .forEach((el) => el.remove());

      const plainText = (clone.innerText || clone.textContent || "").trim();
      const htmlContent = clone.innerHTML.trim();

      if (!plainText) return;

      e.preventDefault();
      e.stopPropagation();

      try {
        // Write both formats — the destination app picks the best one
        await navigator.clipboard.write([
          new ClipboardItem({
            "text/plain": new Blob([plainText], { type: "text/plain" }),
            "text/html": new Blob([htmlContent], { type: "text/html" }),
          }),
        ]);
      } catch (_) {
        // Fallback for browsers that don't support ClipboardItem
        try {
          await navigator.clipboard.writeText(plainText);
        } catch (__) {
          // Last resort: execCommand
          const ta = document.createElement("textarea");
          ta.value = plainText;
          ta.style.cssText = "position:fixed;top:-9999px;opacity:0;";
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          document.body.removeChild(ta);
        }
      }

      // Visual feedback: checkmark
      const original = btn.innerHTML;
      btn.innerHTML =
        '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" ' +
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
        '<polyline points="20 6 9 17 4 12"></polyline></svg>';
      setTimeout(() => {
        btn.innerHTML = original;
      }, 1500);
    },
    true
  );
})();
