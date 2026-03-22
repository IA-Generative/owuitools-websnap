"""
title: Browser Use - Web Extraction & Image Analysis Tool
description: Fetch and extract structured content from web pages, detect login walls, process PDFs, and analyze uploaded images via vision LLM.
author: browser-use
version: 0.3.1
"""

import base64
from pydantic import BaseModel, Field


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
            description="Base URL of the browser-use API service",
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

    async def browser_use(
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
            return result["markdown"]
        else:
            errors = result.get("errors", [])
            error_summary = "\n".join(f"- [{e['stage']}] {e['message']}" for e in errors)
            return f"# Extraction failed\n\n{error_summary}\n\nPartial content:\n\n{result.get('markdown', '')}"

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
