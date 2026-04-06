"""
title: Vision Image Analyzer
description: Analyzes uploaded images via Scaleway VLM (pixtral). No dependency on websnap.
author: miraiku
version: 2.0.0
license: MIT
"""

import base64
import json as _json
from typing import Optional
from pydantic import BaseModel, Field


class Filter:
    class Valves(BaseModel):
        llm_api_url: str = Field(
            default="https://api.scaleway.ai/v1",
            description="URL de l'API LLM (Scaleway Generative APIs)",
        )
        llm_api_key: str = Field(
            default="",
            description="Clé API Scaleway (SCW_SECRET_KEY_LLM)",
        )
        vision_model: str = Field(
            default="pixtral-12b-2409",
            description="Modèle vision à utiliser",
        )
        vision_prompt: str = Field(
            default="Décris cette image en détail dans la même langue que l'utilisateur. Extrais tout texte visible (OCR). Identifie les éléments clés, objets, couleurs, textes, graphiques, diagrammes ou toute information visuelle.",
        )
        timeout: int = Field(default=60, description="Timeout en secondes")
        enabled: bool = Field(default=True)

    def __init__(self):
        self.valves = self.Valves()

    async def _analyze_image(self, image_data_uri: str, prompt: str) -> str | None:
        """Call Scaleway VLM directly to analyze an image."""
        import httpx as _httpx

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_uri}},
                ],
            }
        ]

        async with _httpx.AsyncClient(timeout=self.valves.timeout) as client:
            resp = await client.post(
                f"{self.valves.llm_api_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.valves.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.valves.vision_model,
                    "messages": messages,
                    "max_tokens": 2048,
                },
            )
            if resp.status_code != 200:
                print(f"[VISION] VLM error: {resp.status_code} {resp.text[:200]}")
                return None

            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content if content else None

    def _read_image_from_disk(self, file_id: str, filename: str) -> str | None:
        """Read an uploaded image from OWUI storage and return as base64 data URI."""
        from pathlib import Path
        import mimetypes

        for upload_dir in [Path("/app/backend/data/uploads"), Path("/app/backend/data/cache/files")]:
            if not upload_dir.exists():
                continue
            for fpath in upload_dir.iterdir():
                if fpath.name.startswith(file_id):
                    data = fpath.read_bytes()
                    mime = mimetypes.guess_type(filename)[0] or "image/jpeg"
                    b64 = base64.b64encode(data).decode("utf-8")
                    return f"data:{mime};base64,{b64}"
        return None

    async def inlet(self, body: dict, __user__: Optional[dict] = None, __event_emitter__=None) -> dict:
        if not self.valves.enabled or not self.valves.llm_api_key:
            return body

        messages = body.get("messages", [])
        if not messages:
            return body

        last_msg = messages[-1]
        if last_msg.get("role") != "user":
            return body

        content = last_msg.get("content")

        # Source 1: multimodal content list (image_url items)
        image_urls = []
        text_parts = []
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "image_url":
                    url = item.get("image_url", {}).get("url", "")
                    if url:
                        image_urls.append(url)
                elif item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
        elif isinstance(content, str):
            text_parts.append(content)

        # Source 2: uploaded image files in metadata.files (OWUI puts them here)
        IMAGE_MIMETYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/tiff"}
        metadata_files = body.get("metadata", {}).get("files") or []
        file_infos = []

        for f in metadata_files:
            file_obj = f.get("file", {})
            meta = file_obj.get("meta", {})
            ct = f.get("content_type", "") or meta.get("content_type", "")
            file_id = f.get("id", "") or file_obj.get("id", "")
            filename = f.get("name", "") or file_obj.get("filename", "") or meta.get("name", "image")

            if not file_id or ct not in IMAGE_MIMETYPES:
                continue

            # Read image from disk and convert to data URI
            data_uri = self._read_image_from_disk(file_id, filename)
            if data_uri:
                image_urls.append(data_uri)
                file_infos.append({"id": file_id, "name": filename})
                print(f"[VISION] Found uploaded image: {filename} ({file_id[:12]}...)")

        if not image_urls:
            return body

        user_text = "\n".join(text_parts).strip() or "Analyze these images"
        print(f"[VISION] Found {len(image_urls)} images. Analyzing with {self.valves.vision_model}...")

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Analyzing {len(image_urls)} image(s) with vision model...", "done": False}})

        # Get file IDs from metadata for preview links (complement what we already have)
        if not file_infos:
            file_infos = self._extract_file_ids(body)

        # Analyze each image directly via Scaleway VLM
        analyses = []
        for i, img_url in enumerate(image_urls):
            print(f"[VISION] Analyzing image {i+1}/{len(image_urls)}...")
            try:
                description = await self._analyze_image(img_url, self.valves.vision_prompt)
                if description:
                    file_id = file_infos[i]["id"] if i < len(file_infos) else None
                    file_name = file_infos[i]["name"] if i < len(file_infos) else f"image_{i+1}"
                    analyses.append({
                        "name": file_name,
                        "file_id": file_id,
                        "description": description,
                    })
                    print(f"[VISION] Image {i+1} analyzed OK: {description[:80]}...")
                else:
                    print(f"[VISION] Image {i+1} analysis returned no content")
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

        # Build clickable image reference links
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
            f"- Every time you mention an image in your response, use the EXACT clickable link below.\n"
            f"\n{ref_block}\n\n"
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
            files_raw = parent.get("files") or []
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
