"""
title: WebSnap - Web Extraction & Screenshot Tool
description: Fetch and extract structured content from web pages, take screenshots, compare websites, and analyze uploaded images via vision LLM.
author: websnap
version: 1.1.0
"""

import base64
import html as html_mod
import re
from pydantic import BaseModel, Field


def _normalize_url(url: str) -> str:
    """Add https:// scheme if missing. Handles 'www.example.com' and bare domains."""
    url = url.strip()
    if not url:
        return url
    # Already has a scheme
    if re.match(r"^https?://", url, re.IGNORECASE):
        return url
    # Strip accidental leading slashes
    url = url.lstrip("/")
    # Prefix with https://
    return f"https://{url}"


async def _fetch_owui_image(owui_url: str, file_id: str, content_type: str, user: dict = None) -> str | None:
    """Fetch an uploaded file from OpenWebUI and convert to base64 data URI."""
    import httpx

    headers = {}
    if user and user.get("token"):
        headers["Authorization"] = f"Bearer {user['token']}"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            url = f"{owui_url}/api/v1/files/{file_id}/content"
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                raw = resp.content
                b64 = base64.b64encode(raw).decode("utf-8")
                return f"data:{content_type};base64,{b64}"
    except Exception:
        pass
    return None


def _extract_image_from_messages(messages: list[dict]) -> tuple[str | None, str, str]:
    """Extract image reference from messages. Returns (file_id, content_type, image_name) or (data_uri, '', name)."""
    if not messages:
        return None, "", ""

    for message in reversed(messages):
        # Method 1: OpenWebUI file uploads (files array)
        files = message.get("files", [])
        for f in reversed(files):
            if not isinstance(f, dict):
                continue
            content_type = f.get("content_type", "")
            if not content_type:
                file_meta = f.get("file", {})
                if isinstance(file_meta, dict):
                    content_type = file_meta.get("meta", {}).get("content_type", "")
            file_id = f.get("id", "")
            name = f.get("name", "")
            if content_type.startswith("image/") and file_id:
                return file_id, content_type, name

        # Method 2: OpenAI-style image_url in content list
        content = message.get("content")
        if isinstance(content, list):
            for item in reversed(content):
                if isinstance(item, dict) and item.get("type") == "image_url":
                    url = item.get("image_url", {}).get("url", "")
                    if url:
                        return url, "", ""

        # Method 3: Legacy images array
        images = message.get("images", [])
        if isinstance(images, list):
            for img in reversed(images):
                if isinstance(img, str) and img:
                    return img, "", ""

    return None, "", ""


class Tools:
    class Valves(BaseModel):
        """Configuration knobs exposed in OpenWebUI admin panel."""
        base_url: str = Field(
            default="http://host.docker.internal:8086",
            description="Base URL of the websnap API service (internal, from container)",
        )
        public_url: str = Field(
            default="http://localhost:8086",
            description="Public URL of websnap (accessible from the user browser)",
        )
        openwebui_url: str = Field(
            default="http://localhost:8080",
            description="Base URL of the OpenWebUI instance (for fetching uploaded files). Use http://localhost:8080 when tool runs inside the OpenWebUI container.",
        )
        timeout: int = Field(
            default=60,
            description="Request timeout in seconds",
        )
        use_browser_fallback: bool = Field(
            default=False,
            description="Enable headless browser fallback for JS-heavy pages",
        )
        vision_prompt: str = Field(
            default="Describe this image in detail. Extract any visible text (OCR). Identify key elements, colors, and layout.",
            description="Default prompt sent to vision model for image analysis",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def websnap(
        self,
        url: str,
        __event_emitter__=None,
    ) -> str:
        """
        Fetch a web page and extract its content as clean Markdown.
        Handles HTML pages, PDFs, login detection, and image analysis.

        :param url: The URL to fetch and extract content from.
        :return: Extracted content in Markdown format.
        """
        import httpx

        url = _normalize_url(url)

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Fetching {url}...", "done": False}})

        async with httpx.AsyncClient(timeout=self.valves.timeout) as client:
            response = await client.post(
                f"{self.valves.base_url}/extract",
                json={
                    "url": url,
                    "use_browser_fallback": self.valves.use_browser_fallback,
                },
            )
            response.raise_for_status()
            result = response.json()

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Extraction complete", "done": True}})

        if result.get("ok"):
            markdown = result["markdown"]
            # Strip metadata header (Source, Final URL, Content type, etc.)
            # Keep only content after "## Main content" or after the metadata block
            lines = markdown.split("\n")
            content_start = 0
            for i, line in enumerate(lines):
                if line.startswith("## ") and i > 0:
                    content_start = i
                    break
            if content_start > 0:
                clean = "\n".join(lines[content_start:]).strip()
            else:
                clean = markdown
            meta = result.get("metadata", {})
            source = meta.get("final_url") or meta.get("url", url)
            return f"Source : {source}\n\n{clean}"
        else:
            errors = result.get("errors", [])
            error_summary = "\n".join(f"- [{e['stage']}] {e['message']}" for e in errors)
            return f"# Extraction failed\n\n{error_summary}\n\nPartial content:\n\n{result.get('markdown', '')}"

    async def screenshot(self, url: str, __event_emitter__=None):
        """
        Take a screenshot of a web page and extract its key images.
        Shows a visual preview of the website directly in the chat.
        Use this when the user wants to SEE a website, not just read its text.

        :param url: The URL of the website to screenshot.
        :return: Screenshot and key images from the page.
        """
        import httpx
        from fastapi.responses import HTMLResponse

        url = _normalize_url(url)

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Capturing screenshot of {url}...", "done": False}})

        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout) as client:
                response = await client.post(
                    f"{self.valves.base_url}/screenshot",
                    json={"url": url, "full_page": True, "extract_key_images": True},
                )
                response.raise_for_status()
                result = response.json()
        except Exception as exc:
            return f"# Screenshot error\n\n{exc}"

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Screenshot captured", "done": True}})

        if not result.get("ok"):
            return f"# Screenshot failed\n\n{'; '.join(result.get('errors', []))}"

        title = result.get("title", url)
        description = result.get("description", "")
        screenshot_id = result.get("screenshot_id", "")
        page_text = result.get("page_text", "")
        overlay_actions = result.get("overlay_actions", [])

        # Anti-bot fallback: if screenshot is blank (no text, no title),
        # try HTTP extraction to get the page content
        _is_blank = not page_text and not title
        if _is_blank:
            try:
                if __event_emitter__:
                    await __event_emitter__({"type": "status", "data": {"description": "Page blanche detectee, extraction HTTP en cours...", "done": False}})
                async with httpx.AsyncClient(timeout=self.valves.timeout) as client:
                    extract_resp = await client.post(
                        f"{self.valves.base_url}/extract",
                        json={"url": url, "use_browser_fallback": False},
                    )
                    extract_resp.raise_for_status()
                    extract_result = extract_resp.json()
                if extract_result.get("ok"):
                    md = extract_result.get("markdown", "")
                    meta = extract_result.get("metadata", {})
                    title = title or meta.get("title", url)
                    description = description or meta.get("description", "")
                    page_text = md[:8000] if md else page_text
                    overlay_actions.append("http-fallback: extraction texte via HTTP (anti-bot Playwright)")
            except Exception:
                pass

        public_base = self.valves.public_url.rstrip("/")
        thumb_url = f"{public_base}/screenshots/{screenshot_id}?size=thumb"
        full_url = f"{public_base}/screenshots/{screenshot_id}"

        # Escape values for safe HTML embedding
        safe_title = html_mod.escape(title)
        safe_desc = html_mod.escape(description)
        safe_url = html_mod.escape(url)
        safe_thumb = html_mod.escape(thumb_url)
        safe_full = html_mod.escape(full_url)
        safe_text = html_mod.escape(page_text[:4000]) if page_text else ""

        # Build overlay notice for the HTML card
        overlay_html = ""
        if overlay_actions:
            overlay_items = "".join(
                f"<li>{html_mod.escape(a)}</li>" for a in overlay_actions
            )
            overlay_html = (
                '<div class="overlay-notice">'
                '<span class="badge">Pop-ups fermes automatiquement</span>'
                f"<ul>{overlay_items}</ul>"
                "</div>"
            )

        # Build page text section for the HTML card
        text_html = ""
        if safe_text:
            text_html = (
                '<details class="page-text">'
                "<summary>Contenu textuel de la page</summary>"
                f"<pre>{safe_text}</pre>"
                "</details>"
            )

        # Rich HTML card rendered in sandboxed iframe — LLM never sees this
        html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:#1e1e2e;color:#cdd6f4;padding:12px}}
.card{{border:1px solid #45475a;border-radius:10px;overflow:hidden;
  background:#313244;max-width:640px}}
.card .img-link{{display:block;cursor:pointer}}
.card img{{width:100%;display:block;cursor:zoom-in}}
.card .info{{padding:12px 16px}}
.card .info h3{{font-size:15px;margin-bottom:4px;color:#cdd6f4}}
.card .info p.desc{{font-size:13px;color:#a6adc8;margin-bottom:8px}}
.card .info .src{{font-size:12px;color:#89b4fa;word-break:break-all}}
.card .info .hint{{display:inline-block;margin-top:6px;font-size:11px;
  color:#a6adc8;font-style:italic}}
.overlay-notice{{margin-top:10px;padding:8px 12px;background:#45475a;
  border-radius:6px;font-size:12px;color:#f9e2af}}
.overlay-notice .badge{{font-weight:600;display:block;margin-bottom:4px}}
.overlay-notice ul{{margin:0;padding-left:18px;color:#a6adc8;font-size:11px}}
.page-text{{margin-top:10px;border-top:1px solid #45475a;padding-top:8px}}
.page-text summary{{cursor:pointer;font-size:13px;font-weight:500;color:#89b4fa}}
.page-text summary:hover{{text-decoration:underline}}
.page-text pre{{margin-top:8px;font-size:12px;line-height:1.5;color:#bac2de;
  white-space:pre-wrap;word-break:break-word;max-height:400px;overflow-y:auto;
  background:#1e1e2e;padding:10px;border-radius:6px}}
</style></head><body>
<div class="card">
  <div class="img-link" onclick="openUrl('{safe_full}')">
    <img src="{safe_thumb}" alt="Screenshot de {safe_title}" loading="lazy">
  </div>
  <div class="info">
    <h3>{safe_title}</h3>
    {"<p class='desc'>" + safe_desc + "</p>" if description else ""}
    <span class="src">{safe_url}</span><br>
    <span class="hint">Cliquez sur l'image pour la visualiser en taille reelle</span>
    {overlay_html}
    {text_html}
  </div>
</div>
<script>
function openUrl(url) {{
  window.open(url, '_blank') || window.parent.postMessage({{type:'open-url', url: url}}, '*');
}}
const ro = new ResizeObserver(()=>{{
  window.parent.postMessage({{type:'iframe-resize',
    height:document.documentElement.scrollHeight}},'*');
}});
ro.observe(document.body);
document.querySelector('details')?.addEventListener('toggle', ()=>{{
  window.parent.postMessage({{type:'iframe-resize',
    height:document.documentElement.scrollHeight}},'*');
}});
</script>
</body></html>"""

        # Truncate page text for LLM context (keep it under ~2000 chars)
        context_text = page_text[:2000] if page_text else ""

        # Compact JSON context for the LLM — no URLs (rendered in the card above),
        # just metadata + text so the LLM describes the content
        context = {
            "status": "success",
            "source_url": url,
            "page_title": title,
            "caption": description or f"Capture d'ecran de {title}",
            "note": "L'apercu visuel est affiche au-dessus. Pour le voir en grand, l'utilisateur peut cliquer sur l'image.",
            "page_text": context_text,
        }
        if overlay_actions:
            context["overlay_dismissed"] = overlay_actions

        # HTMLResponse renders the card in a sandboxed iframe (images load directly)
        # Context JSON goes to the LLM for generating its text response
        return (
            HTMLResponse(
                content=html_content,
                headers={"Content-Disposition": "inline"},
            ),
            context,
        )

    async def compare_urls(
        self,
        urls: str,
        __event_emitter__=None,
    ) -> str:
        """
        Fetch and compare multiple web pages side by side.
        Provide a comma-separated list of URLs to extract and compare their content.
        Useful for comparing services, products, documentation, or any web pages.

        :param urls: Comma-separated list of URLs to compare (e.g. "https://site1.com, https://site2.com, https://site3.com").
        :return: Extracted content from all URLs, ready for comparison.
        """
        import asyncio
        import httpx

        url_list = [_normalize_url(u.strip()) for u in urls.split(",") if u.strip()]
        if not url_list:
            return "# No URLs provided\n\nPlease provide a comma-separated list of URLs."

        if len(url_list) > 5:
            url_list = url_list[:5]

        results = []

        async with httpx.AsyncClient(timeout=self.valves.timeout) as client:
            for i, url in enumerate(url_list, 1):
                if __event_emitter__:
                    await __event_emitter__({"type": "status", "data": {"description": f"Fetching {i}/{len(url_list)}: {url}...", "done": False}})

                try:
                    response = await client.post(
                        f"{self.valves.base_url}/extract",
                        json={
                            "url": url,
                            "use_browser_fallback": self.valves.use_browser_fallback,
                        },
                    )
                    response.raise_for_status()
                    result = response.json()

                    if result.get("ok"):
                        # Truncate to avoid context overflow
                        content = result["markdown"]
                        if len(content) > 24000:
                            content = content[:24000] + "\n\n*[Content truncated for comparison]*"
                        results.append(f"## Site {i}: {url}\n\n{content}")
                    else:
                        errors = result.get("errors", [])
                        err_msg = "; ".join(e["message"] for e in errors)
                        results.append(f"## Site {i}: {url}\n\n*Extraction failed: {err_msg}*")
                except Exception as exc:
                    results.append(f"## Site {i}: {url}\n\n*Error: {exc}*")

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Extracted {len(url_list)} sites", "done": True}})

        header = f"# Comparison of {len(url_list)} websites\n\n"
        return header + "\n\n---\n\n".join(results)

    async def analyze_image(
        self,
        query: str = "",
        __messages__: list[dict] = None,
        __user__: dict = None,
        __event_emitter__=None,
    ) -> str:
        """
        Analyze an uploaded image using a vision model.
        Upload an image in the chat then call this tool to get a detailed
        description, OCR text extraction, and content analysis.

        :param query: Optional question about the image (e.g. "What text is visible?" or "Describe the chart").
        :return: Detailed analysis of the uploaded image.
        """
        import httpx

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Looking for uploaded image...", "done": False}})

        # Extract image reference from messages
        image_ref, content_type, image_name = _extract_image_from_messages(__messages__)

        if not image_ref:
            return (
                "# No image found\n\n"
                "I could not find an uploaded image in this conversation.\n"
                "Please upload an image (PNG, JPG, etc.) in the chat and try again."
            )

        # If image_ref is a file ID (not a data URI), fetch the file from OpenWebUI
        if not image_ref.startswith("data:") and not image_ref.startswith("http"):
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"Downloading {image_name or 'image'}...", "done": False}})
            image_data_uri = await _fetch_owui_image(
                self.valves.openwebui_url, image_ref, content_type, __user__
            )
            if not image_data_uri:
                return f"# Failed to fetch image\n\nCould not download file {image_ref} from OpenWebUI."
        else:
            image_data_uri = image_ref

        if __event_emitter__:
            desc = f"Analyzing image{' (' + image_name + ')' if image_name else ''}..."
            await __event_emitter__({"type": "status", "data": {"description": desc, "done": False}})

        prompt = query if query else self.valves.vision_prompt

        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout) as client:
                response = await client.post(
                    f"{self.valves.base_url}/analyze-image",
                    json={
                        "image_data": image_data_uri,
                        "prompt": prompt,
                    },
                )
                response.raise_for_status()
                result = response.json()
        except Exception as exc:
            return f"# Image analysis error\n\n{exc}"

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Image analysis complete", "done": True}})

        if result.get("ok"):
            parts = [f"# Image Analysis{' — ' + image_name if image_name else ''}\n"]
            if result.get("description"):
                parts.append(result["description"])
            if result.get("visible_text"):
                parts.append(f"\n## Visible Text (OCR)\n\n{result['visible_text']}")
            return "\n".join(parts)
        else:
            error = result.get("error", "Unknown error")
            return f"# Image analysis failed\n\n{error}"
