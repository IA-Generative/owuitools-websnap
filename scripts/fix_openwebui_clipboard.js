// Fix OpenWebUI copy button: write both text/plain AND text/html to clipboard.
//
// Deploy: inject inline in index.html or mount as loader.js
//
// When OpenWebUI copies raw markdown, this intercepts the call and writes:
//   - text/plain: clean rendered text (for Notepad, Terminal)
//   - text/html: formatted HTML (for Word, Outlook, Google Docs)
//
(function(){
  try {
    var _orig = Clipboard.prototype.writeText;
    Clipboard.prototype.writeText = async function(text) {
      var blocks = document.querySelectorAll(".markdown-prose, .prose");
      var match = null;
      for (var i = 0; i < blocks.length; i++) {
        var p = (blocks[i].innerText || "").trim();
        if (p.length < 20 || text.length < 20) continue;
        var a = text.replace(/^#+ /gm, "").replace(/\*\*/g, "").substring(0,40).trim();
        if (p.indexOf(a) !== -1) {
          match = blocks[i];
          break;
        }
      }
      if (match) {
        var c = match.cloneNode(true);
        c.querySelectorAll("button").forEach(function(e){e.remove();});
        var ct = (c.innerText || "").trim();
        var ch = c.innerHTML.trim();
        try {
          await navigator.clipboard.write([new ClipboardItem({
            "text/plain": new Blob([ct], {type:"text/plain"}),
            "text/html": new Blob([ch], {type:"text/html"})
          })]);
          return;
        } catch(e2) {
          return _orig.call(this, ct);
        }
      }
      return _orig.call(this, text);
    };
    navigator.clipboard.__patched = true;
    console.log("[loader.js] Clipboard patched OK");
  } catch(err) {
    console.error("[loader.js] Patch failed:", err);
  }
})();
