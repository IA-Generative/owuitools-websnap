"""
Jeu de test pour le skill Browser Use déployé dans OpenWebUI.

Ce script teste le tool via l'API OpenWebUI et directement via l'API browser-use.
Usage:
    source .venv/bin/activate
    python tests/test_openwebui_skill.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx

# Configuration
BROWSER_USE_URL = "http://localhost:8086"
OPENWEBUI_URL = "http://localhost:3000"

# ─────────────────────────────────────────────────
# Jeu de test : cas variés pour valider le skill
# ─────────────────────────────────────────────────

TEST_CASES = [
    # ── Pages HTML standard ──
    {
        "name": "Page simple (example.com)",
        "url": "https://example.com/",
        "expect_ok": True,
        "expect_contains": ["Example Domain"],
        "category": "html",
    },
    {
        "name": "Wikipedia FR — article long",
        "url": "https://fr.wikipedia.org/wiki/Intelligence_artificielle",
        "expect_ok": True,
        "expect_contains": ["intelligence artificielle", "Intelligence artificielle"],
        "expect_min_length": 500,
        "category": "html",
    },
    {
        "name": "Wikipedia EN — Web scraping",
        "url": "https://en.wikipedia.org/wiki/Web_scraping",
        "expect_ok": True,
        "expect_contains": ["Web scraping", "scraping"],
        "category": "html",
    },

    # ── Page avec images ──
    {
        "name": "Wikipedia Earth — page riche en images",
        "url": "https://en.wikipedia.org/wiki/Earth",
        "expect_ok": True,
        "expect_contains": ["Earth"],
        "expect_min_length": 500,
        "category": "images",
    },

    # ── PDF ──
    {
        "name": "PDF arxiv — Attention Is All You Need",
        "url": "https://arxiv.org/pdf/1706.03762v5",
        "expect_ok": True,
        "expect_contains": ["Attention"],
        "category": "pdf",
    },

    # ── SPA / JS-heavy (sans browser fallback) ──
    {
        "name": "SPA React.dev — contenu limité sans browser",
        "url": "https://react.dev/",
        "expect_ok": None,  # peut être ok=True ou ok=False
        "category": "spa",
    },

    # ── Sécurité SSRF ──
    {
        "name": "SSRF — localhost rejeté",
        "url": "http://127.0.0.1/admin",
        "expect_ok": False,
        "expect_error_stage": "fetch",
        "category": "security",
    },
    {
        "name": "SSRF — metadata AWS rejeté",
        "url": "http://169.254.169.254/latest/meta-data/",
        "expect_ok": False,
        "expect_error_stage": "fetch",
        "category": "security",
    },
    {
        "name": "SSRF — réseau privé rejeté",
        "url": "http://192.168.1.1/",
        "expect_ok": False,
        "expect_error_stage": "fetch",
        "category": "security",
    },
    {
        "name": "SSRF — scheme file:// rejeté",
        "url": "file:///etc/passwd",
        "expect_ok": False,
        "expect_error_stage": "fetch",
        "category": "security",
    },
    {
        "name": "SSRF — credentials dans URL rejetés",
        "url": "http://user:pass@example.com/",
        "expect_ok": False,
        "expect_error_stage": "fetch",
        "category": "security",
    },

    # ── URL invalides ──
    {
        "name": "URL vide",
        "url": "",
        "expect_ok": False,
        "category": "validation",
    },
    {
        "name": "URL sans schéma",
        "url": "example.com",
        "expect_ok": False,
        "category": "validation",
    },

    # ── Cas edge ──
    {
        "name": "Texte brut — RFC",
        "url": "https://www.rfc-editor.org/rfc/rfc9110.txt",
        "expect_ok": True,
        "category": "edge",
    },
]


def print_result(name: str, passed: bool, detail: str = ""):
    icon = "✅" if passed else "❌"
    detail_str = f" — {detail}" if detail else ""
    print(f"  {icon} {name}{detail_str}")


async def test_direct_api():
    """Test le skill directement via l'API browser-use."""
    print("\n" + "=" * 60)
    print("  TEST DIRECT API (browser-use sur port 8086)")
    print("=" * 60)

    passed = 0
    failed = 0
    skipped = 0

    async with httpx.AsyncClient(timeout=60) as client:
        for tc in TEST_CASES:
            name = tc["name"]
            try:
                r = await client.post(
                    f"{BROWSER_USE_URL}/extract",
                    json={"url": tc["url"]},
                )
                data = r.json()

                ok = data.get("ok")
                markdown = data.get("markdown", "")
                errors = data.get("errors", [])

                checks_passed = True
                details = []

                # Check ok status
                if tc.get("expect_ok") is not None:
                    if ok != tc["expect_ok"]:
                        checks_passed = False
                        details.append(f"expected ok={tc['expect_ok']}, got ok={ok}")

                # Check contains
                for keyword in tc.get("expect_contains", []):
                    if keyword.lower() not in markdown.lower():
                        checks_passed = False
                        details.append(f"missing '{keyword}'")
                        break

                # Check min length
                min_len = tc.get("expect_min_length", 0)
                if min_len and len(markdown) < min_len:
                    checks_passed = False
                    details.append(f"too short: {len(markdown)} < {min_len}")

                # Check error stage
                if tc.get("expect_error_stage") and errors:
                    if errors[0]["stage"] != tc["expect_error_stage"]:
                        checks_passed = False
                        details.append(f"wrong error stage: {errors[0]['stage']}")

                detail = ", ".join(details) if details else f"md={len(markdown)}ch"
                print_result(name, checks_passed, detail)

                if checks_passed:
                    passed += 1
                else:
                    failed += 1

            except Exception as exc:
                print_result(name, False, f"EXCEPTION: {exc}")
                failed += 1

    print(f"\n  Résultats: {passed} passés, {failed} échoués, {skipped} ignorés")
    return passed, failed


async def test_healthcheck():
    """Test le endpoint healthcheck."""
    print("\n" + "=" * 60)
    print("  HEALTHCHECK")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BROWSER_USE_URL}/healthz")
        data = r.json()
        healthy = data.get("status") == "healthy"
        features = data.get("features", [])
        print_result("Healthcheck", healthy, f"status={data['status']}, features={features}")
        return 1 if healthy else 0, 0 if healthy else 1


async def test_openwebui_tool_registered():
    """Vérifie que le tool est enregistré dans OpenWebUI."""
    print("\n" + "=" * 60)
    print("  OPENWEBUI — TOOL REGISTRATION")
    print("=" * 60)

    try:
        # Generate JWT
        import jwt
        secret = "ad8087b577b425720c0387628914d5a3a4bd5445cb917caaa824868ef752d7008928300dd4777f0ac3527f0946f13147"
        token = jwt.encode(
            {
                "id": "68c961e0-3ecf-460b-984e-477d6e31df61",
                "email": "user1@test.local",
                "role": "admin",
                "exp": int(time.time()) + 3600,
                "iat": int(time.time()),
            },
            secret,
            algorithm="HS256",
        )

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{OPENWEBUI_URL}/api/v1/tools/",
                headers={"Authorization": f"Bearer {token}"},
            )
            tools = r.json()
            tool_ids = [t["id"] for t in tools]
            found = "browser_use" in tool_ids
            print_result(
                "Tool 'browser_use' enregistré",
                found,
                f"tools trouvés: {tool_ids}",
            )

            if found:
                tool = next(t for t in tools if t["id"] == "browser_use")
                has_meta = bool(tool.get("meta", {}).get("manifest", {}).get("title"))
                print_result(
                    "Métadonnées du tool complètes",
                    has_meta,
                    f"title={tool['meta'].get('manifest', {}).get('title', 'MISSING')}",
                )

            return (1 if found else 0), (0 if found else 1)
    except ImportError:
        print_result("OpenWebUI check", False, "pyjwt not installed")
        return 0, 1
    except Exception as exc:
        print_result("OpenWebUI check", False, f"EXCEPTION: {exc}")
        return 0, 1


async def main():
    print("\n" + "🔧" * 30)
    print("  JEU DE TEST — Browser Use Skill")
    print("🔧" * 30)

    total_passed = 0
    total_failed = 0

    # 1. Healthcheck
    p, f = await test_healthcheck()
    total_passed += p
    total_failed += f

    # 2. OpenWebUI tool registration
    p, f = await test_openwebui_tool_registered()
    total_passed += p
    total_failed += f

    # 3. Direct API tests
    p, f = await test_direct_api()
    total_passed += p
    total_failed += f

    # Summary
    print("\n" + "=" * 60)
    total = total_passed + total_failed
    print(f"  TOTAL: {total_passed}/{total} passés")
    if total_failed:
        print(f"  ⚠️  {total_failed} test(s) en échec")
    else:
        print("  🎉 Tous les tests sont passés !")
    print("=" * 60)

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
