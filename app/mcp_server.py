"""
MCP server for websnap — Streamable HTTP transport.
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("websnap")


@mcp.tool()
async def browser_extract(url: str, format: str = "markdown") -> str:
    """Extrait le contenu d'une page web : texte, markdown, métadonnées.

    :param url: URL de la page web à extraire
    :param format: Format de sortie (text, markdown, html)
    """
    from app.api import extract
    from app.models import ExtractRequest
    try:
        req = ExtractRequest(url=url, output_format=format)
        result = await extract(req)
        content = getattr(result, "content", None) or getattr(result, "text", None) or str(result)
        return content
    except Exception as e:
        return f"Erreur lors de l'extraction de {url} : {e}"


@mcp.tool()
async def browser_analyze_image(image_url: str, question: str = "Décris cette image en détail.") -> str:
    """Analyse une image accessible via URL et retourne une description.

    :param image_url: URL de l'image à analyser
    :param question: Question spécifique sur l'image
    """
    from app.api import analyze_image
    from app.models import ImageAnalyzeRequest
    try:
        req = ImageAnalyzeRequest(image_url=image_url, question=question)
        result = await analyze_image(req)
        return getattr(result, "description", None) or str(result)
    except Exception as e:
        return f"Erreur lors de l'analyse de l'image : {e}"
