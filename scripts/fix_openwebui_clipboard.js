// Fix OpenWebUI copy button: write text/plain (with proper formatting) + text/html
//
// Deploy: inject inline in index.html (loader.js blocked by CORS)
// See prompts/guide_fix_clipboard_openwebui.md for full deployment guide.
//
// Clipboard output:
//   text/plain → clean text, tables as tab-separated columns, numbered lists
//   text/html  → rendered HTML (for Word, Outlook, Google Docs)
//
(function(){
  try {
    var _orig = Clipboard.prototype.writeText;

    function htmlToPlainText(el) {
      var clone = el.cloneNode(true);
      clone.querySelectorAll("button, .copy-button, svg").forEach(function(e){e.remove();});

      // --- Handle tables: convert to tab-separated columns ---
      clone.querySelectorAll("table").forEach(function(table) {
        var rows = [];
        table.querySelectorAll("tr").forEach(function(tr) {
          var cells = [];
          tr.querySelectorAll("th, td").forEach(function(td) {
            cells.push(td.textContent.trim());
          });
          rows.push(cells.join("\t"));
        });
        // Add separator line after header
        if (rows.length > 1) {
          var hdr = rows[0].split("\t");
          var sep = hdr.map(function(h){ return "---"; }).join("\t");
          rows.splice(1, 0, sep);
        }
        var textNode = document.createTextNode("\n" + rows.join("\n") + "\n");
        table.replaceWith(textNode);
      });

      // --- Handle code blocks: preserve as-is with indent ---
      clone.querySelectorAll("pre").forEach(function(pre) {
        var code = pre.textContent || "";
        pre.replaceWith(document.createTextNode("\n" + code + "\n"));
      });

      // --- Handle lists ---
      clone.querySelectorAll("li").forEach(function(li) {
        var depth = 0;
        var parent = li.parentElement;
        while (parent && parent !== clone) {
          if (parent.tagName === "UL" || parent.tagName === "OL") depth++;
          parent = parent.parentElement;
        }
        var indent = "  ".repeat(Math.max(0, depth - 1));
        var bullet = li.parentElement && li.parentElement.tagName === "OL" ? 
          (Array.from(li.parentElement.children).indexOf(li) + 1) + ". " : "\u2022 ";
        li.prepend(document.createTextNode(indent + bullet));
        li.append(document.createTextNode("\n"));
      });

      // --- Block elements: newline before/after ---
      clone.querySelectorAll("h1,h2,h3,h4,h5,h6,p,blockquote").forEach(function(b) {
        b.prepend(document.createTextNode("\n"));
        b.append(document.createTextNode("\n"));
      });
      clone.querySelectorAll("br").forEach(function(b){ b.replaceWith("\n"); });
      clone.querySelectorAll("hr").forEach(function(b){ b.replaceWith("\n---\n"); });

      var text = clone.textContent || "";
      text = text.replace(/\n{3,}/g, "\n\n");
      text = text.split("\n").map(function(l){
        return l.replace(/^\s+/, function(spaces){
          // Preserve indentation for code/lists, trim others
          return spaces.indexOf("\t") !== -1 || spaces.length <= 4 ? spaces : "";
        }).trimEnd();
      }).join("\n");
      return text.trim();
    }

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
        var ct = htmlToPlainText(match);
        var clone2 = match.cloneNode(true);
        clone2.querySelectorAll("button, .copy-button, svg").forEach(function(e){e.remove();});
        var ch = clone2.innerHTML.trim();
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
