"""
title: Vision Image Analyzer
description: Analyzes uploaded images via Scaleway VLM (pixtral). No dependency on websnap.
author: miraiku
version: 3.0.0
license: MIT
"""

import base64
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

log = logging.getLogger("vision_filter")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}
IMAGE_MIMETYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/tiff"}


class Filter:
    class Valves(BaseModel):
        llm_api_url: str = Field(default="https://api.scaleway.ai/v1", description="URL de l'API LLM")
        llm_api_key: str = Field(default="", description="Clé API Scaleway")
        vision_model: str = Field(default="pixtral-12b-2409", description="Modèle vision")
        timeout: int = Field(default=120, description="Timeout en secondes")
        enabled: bool = Field(default=True)

    def __init__(self):
        self.valves = self.Valves()

    def _find_images(self, body: dict) -> list[dict]:
        """Find uploaded images from all sources in the body."""
        images = []
        seen = set()

        # Source 1: metadata.files
        for f in (body.get("metadata", {}).get("files") or []):
            info = self._extract_image_info(f)
            if info and info["id"] not in seen:
                seen.add(info["id"])
                images.append(info)

        # Source 2: body.files
        for f in (body.get("files") or []):
            info = self._extract_image_info(f)
            if info and info["id"] not in seen:
                seen.add(info["id"])
                images.append(info)

        # Source 3: last user message content (multimodal image_url)
        messages = body.get("messages") or []
        if messages:
            last = messages[-1]
            if last.get("role") == "user" and isinstance(last.get("content"), list):
                for item in last["content"]:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        url = item.get("image_url", {}).get("url", "")
                        if url and url not in seen:
                            seen.add(url)
                            images.append({"id": url, "name": "inline_image", "content_type": "image/jpeg", "data_uri": url})

        return images

    def _extract_image_info(self, f: dict) -> Optional[dict]:
        """Extract image info from a file entry."""
        file_obj = f.get("file", {})
        meta = file_obj.get("meta", {})

        name = f.get("name", "") or file_obj.get("filename", "") or meta.get("name", "")
        ct = f.get("content_type", "") or meta.get("content_type", "")
        file_id = f.get("id", "") or file_obj.get("id", "")

        if not file_id or not name:
            return None

        # Check by mimetype or extension
        ext = ("." + name.rsplit(".", 1)[-1]).lower() if "." in name else ""
        if ct not in IMAGE_MIMETYPES and ext not in IMAGE_EXTENSIONS:
            return None

        return {"id": file_id, "name": name, "content_type": ct or "image/jpeg"}

    def _read_image(self, file_id: str, filename: str) -> Optional[str]:
        """Read image from OWUI uploads dir and return as base64 data URI."""
        import mimetypes

        for upload_dir in [Path("/app/backend/data/uploads"), Path("/app/backend/data/cache/files")]:
            if not upload_dir.exists():
                continue
            for fpath in upload_dir.iterdir():
                if fpath.name.startswith(file_id):
                    data = fpath.read_bytes()
                    mime = mimetypes.guess_type(filename)[0] or "image/jpeg"
                    b64 = base64.b64encode(data).decode("utf-8")
                    log.info(f"Read image {filename}: {len(data)} bytes → {len(b64)} base64 chars")
                    return f"data:{mime};base64,{b64}"
        return None

    async def _call_vlm(self, data_uri: str, prompt: str) -> Optional[str]:
        """Call Scaleway VLM with an image."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout) as client:
                resp = await client.post(
                    f"{self.valves.llm_api_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.valves.llm_api_key}", "Content-Type": "application/json"},
                    json={
                        "model": self.valves.vision_model,
                        "messages": [{"role": "user", "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": data_uri}},
                        ]}],
                        "max_tokens": 2048,
                    },
                )
                if resp.status_code != 200:
                    log.error(f"VLM error {resp.status_code}: {resp.text[:200]}")
                    return None
                return resp.json().get("choices", [{}])[0].get("message", {}).get("content")
        except Exception as e:
            log.error(f"VLM call failed: {e}")
            return None

    async def inlet(self, body: dict, __user__: Optional[dict] = None, __event_emitter__=None) -> dict:
        if not self.valves.enabled:
            return body

        images = self._find_images(body)
        if not images:
            return body

        log.info(f"Found {len(images)} image(s): {[img['name'] for img in images]}")

        if not self.valves.llm_api_key:
            log.warning("No API key configured — skipping vision analysis")
            return body

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Analyzing {len(images)} image(s) with {self.valves.vision_model}...", "done": False}})

        # Get user text
        messages = body.get("messages") or []
        last_msg = messages[-1] if messages else {}
        user_text = ""
        content = last_msg.get("content")
        if isinstance(content, str):
            user_text = content
        elif isinstance(content, list):
            user_text = " ".join(item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text")

        prompt = user_text.strip() or "Décris cette image en détail. Extrais tout texte visible (OCR)."

        analyses = []
        for img in images:
            # Get data URI (either already inline or read from disk)
            data_uri = img.get("data_uri")
            if not data_uri:
                data_uri = self._read_image(img["id"], img["name"])
            if not data_uri:
                log.warning(f"Could not read image {img['name']} ({img['id'][:12]})")
                continue

            log.info(f"Calling VLM for {img['name']} ({len(data_uri)} chars)")
            description = await self._call_vlm(data_uri, prompt)
            if description:
                analyses.append({"name": img["name"], "id": img["id"], "description": description})
                log.info(f"VLM OK for {img['name']}: {description[:80]}...")
            else:
                log.warning(f"VLM returned no content for {img['name']}")

        if not analyses:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Vision analysis returned no results", "done": True}})
            return body

        # Build injection
        parts = []
        for i, a in enumerate(analyses, 1):
            ref = f"[🖼️ Image {i}](/api/v1/files/{a['id']}/content)" if not a["id"].startswith("data:") else f"Image {i}"
            parts.append(f"### {ref}: {a['name']}\n{a['description']}")

        injection = (
            f"\n\n<image_analysis>\n"
            f"{len(analyses)} image(s) analysée(s) :\n\n"
            + "\n\n---\n\n".join(parts)
            + "\n\nRéponds dans la MÊME LANGUE que l'utilisateur. Utilise les liens ci-dessus pour référencer les images.\n"
            f"</image_analysis>"
        )

        # Inject into last user message
        if last_msg.get("role") == "user":
            if isinstance(last_msg.get("content"), list):
                last_msg["content"] = user_text + injection
            else:
                last_msg["content"] = (last_msg.get("content") or "") + injection

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Analyzed {len(analyses)} image(s)", "done": True}})

        log.info(f"Injected {len(analyses)} analysis/analyses")
        return body

    async def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        return body
