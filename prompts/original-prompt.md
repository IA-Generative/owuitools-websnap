# 🧠 Prompt complet — Browser Skill industriel (Scaleway + OpenWebUI + Kubernetes)

## 🎯 Contexte

Ce prompt est destiné à générer automatiquement, via Codex ou Claude Code, un **microservice de type “browser-use skill”** :

- Extraction web intelligente
- Gestion des pages de login
- Traitement PDF + images
- Intégration LLM (Scaleway)
- Déploiement Docker + Kubernetes
- Tests fonctionnels, sécurité et charge

---

## 🚀 PROMPT À UTILISER

```text
You are a senior platform engineer, expert in Python, Kubernetes, DevSecOps, and LLM integration.

Your task is to generate a FULL production-ready project for a "browser-use skill" compatible with OpenWebUI.

This system must be secure, scalable, and designed for Kubernetes deployment.

---

# 🎯 OBJECTIVE

Build a complete system that:

- Extracts structured content from web pages
- Handles login detection and authentication
- Processes PDFs and images
- Uses Scaleway LLM APIs via OpenAI-compatible interface
- Runs in Docker and Kubernetes
- Includes testing, security validation, and stress testing

---

# 🔐 ENVIRONMENT VARIABLES (MANDATORY)

The system MUST use the following environment variables:

```bash
SCW_SECRET_KEY_LLM=
SCW_LLM_BASE_URL=https://api.scaleway.ai/v1
SCW_LLM_MODEL=gpt-oss-120b
SCW_LLM_VISION_MODEL=mistral/pixtral-12b-2409