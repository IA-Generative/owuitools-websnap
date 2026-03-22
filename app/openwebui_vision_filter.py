"""
title: Vision Image Analyzer
description: Analyzes uploaded images via vision LLM. Injects descriptions and image previews for text-only models.
author: browser-use
version: 1.5.0
license: MIT
"""

import base64
import json as _json
from typing import Optional
from pydantic import BaseModel, Field


class Filter:
    class Valves(BaseModel):
        vision_api_url: str = Field(default="http://host.docker.internal:8086/analyze-image")
        timeout: int = Field(default=60)
        vision_prompt: str = Field(default="Décris cette image en détail dans la même langue que l'utilisateur. Extrais tout texte visible (OCR). Identifie les éléments clés, objets, couleurs, textes, graphiques, diagrammes ou toute information visuelle.")
        enabled: bool = Field(default=True)

    def __init__(self):
        self.valves = self.Valves()

    async def inlet(self, body: dict, __user__: Optional[dict] = None, __event_emitter__=None) -> dict:
        if not self.valves.enabled:
            return body

        messages = body.get("messages", [])
        if not messages:
            return body

        last_msg = messages[-1]
        if last_msg.get("role") != "user":
            return body

        content = last_msg.get("content")
        if not isinstance(content, list):
            return body

        # Extract image_url items and text from content list
        image_urls = []
        text_parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "image_url":
                url = item.get("image_url", {}).get("url", "")
                if url:
                    image_urls.append(url)
            elif item.get("type") == "text":
                text_parts.append(item.get("text", ""))

        if not image_urls:
            return body

        user_text = "\n".join(text_parts).strip() or "Analyze these images"
        print(f"[VISION] Found {len(image_urls)} images. Analyzing...")

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Analyzing {len(image_urls)} image(s) with vision model...", "done": False}})

        # Get file IDs from metadata for preview links
        file_infos = self._extract_file_ids(body)

        # Analyze each image
        import httpx as _httpx
        analyses = []
        for i, img_url in enumerate(image_urls):
            print(f"[VISION] Analyzing image {i+1}/{len(image_urls)}...")
            try:
                async with _httpx.AsyncClient(timeout=self.valves.timeout) as client:
                    resp = await client.post(
                        self.valves.vision_api_url,
                        json={"image_data": img_url, "prompt": self.valves.vision_prompt},
                    )
                    if resp.status_code == 200:
                        result = resp.json()
                        if result.get("ok") and result.get("description"):
                            file_id = file_infos[i]["id"] if i < len(file_infos) else None
                            file_name = file_infos[i]["name"] if i < len(file_infos) else f"image_{i+1}"
                            analyses.append({
                                "name": file_name,
                                "file_id": file_id,
                                "description": result["description"],
                            })
                            print(f"[VISION] Image {i+1} analyzed OK: {result['description'][:80]}...")
                        else:
                            print(f"[VISION] Image {i+1} analysis failed: {result.get('error', 'no description')}")
            except Exception as e:
                print(f"[VISION] Image {i+1} error: {e}")

        if not analyses:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Vision analysis returned no results", "done": True}})
            return body

        # Build analysis text
        parts = []
        for idx, a in enumerate(analyses, 1):
            parts.append(f"### Image {idx}: {a['name']}\n{a['description']}")

        analysis_block = "\n\n---\n\n".join(parts)

        # Build clickable image reference links for inline use
        ref_lines = []
        for idx, a in enumerate(analyses, 1):
            if a.get("file_id"):
                furl = f"/api/v1/files/{a['file_id']}/content"
                ref_lines.append(f"- Image {idx} = [🖼️ Image {idx}]({furl})")

        ref_block = "\n".join(ref_lines) if ref_lines else ""

        injection = (
            f"\n\n<image_analysis>\n"
            f"{len(analyses)} image(s) analyzed by vision model:\n\n"
            f"{analysis_block}\n\n"
            f"FORMATTING INSTRUCTIONS (CRITICAL — follow precisely):\n"
            f"- ALWAYS respond in the SAME LANGUAGE as the user's message.\n"
            f"- Every time you mention an image in your response, use the EXACT clickable link below instead of plain text.\n"
            f"  Do NOT write 'Image 1' as plain text. ALWAYS write it as the markdown link.\n"
            f"  Do NOT modify the URLs. Do NOT add a domain. Copy each link character for character.\n"
            f"\n{ref_block}\n\n"
            f"Example: instead of writing 'Image 1 shows a cat', write '[🖼️ Image 1](/api/v1/files/xxx/content) shows a cat'.\n"
            f"</image_analysis>"
        )

        # Replace content list with text + injection
        last_msg["content"] = user_text + injection
        messages[-1] = last_msg
        body["messages"] = messages

        print(f"[VISION] Injected {len(analyses)} analyses into message")

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Analyzed {len(analyses)} image(s)", "done": True}})

        return body

    async def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        return body

    def _extract_file_ids(self, body: dict) -> list[dict]:
        """Extract file IDs and names from metadata.parent_message.files."""
        try:
            metadata = body.get("metadata", {})
            parent = metadata.get("parent_message", {})
            files_raw = parent.get("files", [])
            if isinstance(files_raw, str):
                import ast
                files_raw = ast.literal_eval(files_raw)
            result = []
            for f in files_raw:
                if isinstance(f, dict):
                    file_obj = f.get("file", {})
                    file_id = f.get("id", "") or file_obj.get("id", "")
                    file_name = f.get("name", "") or file_obj.get("filename", "") or file_obj.get("meta", {}).get("name", "image")
                    if file_id:
                        result.append({"id": file_id, "name": file_name})
            return result
        except Exception as e:
            print(f"[VISION] Error extracting file IDs: {e}")
            return []