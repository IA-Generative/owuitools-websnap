#!/usr/bin/env bash
# Register (or update) the browser-use Tool and Vision Filter in OpenWebUI.
# Requires: WEBUI_SECRET_KEY, WEBUI_USER_ID, WEBUI_USER_EMAIL in env or .env
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

OPENWEBUI_URL="${OPENWEBUI_URL:-http://localhost:3000}"
BROWSER_USE_URL="${BROWSER_USE_URL:-http://host.docker.internal:8086}"

# ── Load .env if present ──────────────────────────────────────
if [[ -f "${PROJECT_ROOT}/.env.test" ]]; then
  set -a; source "${PROJECT_ROOT}/.env.test"; set +a
fi

# ── Validate required env ─────────────────────────────────────
if [[ -z "${WEBUI_SECRET_KEY:-}" ]]; then
  echo "ERROR: WEBUI_SECRET_KEY is required."
  echo "Set it in environment or in ${PROJECT_ROOT}/.env.test"
  exit 1
fi

WEBUI_USER_ID="${WEBUI_USER_ID:-68c961e0-3ecf-460b-984e-477d6e31df61}"
WEBUI_USER_EMAIL="${WEBUI_USER_EMAIL:-user1@test.local}"

# ── Generate JWT ──────────────────────────────────────────────
TOKEN=$(python3 -c "
import jwt, time, sys
token = jwt.encode(
    {'id': '${WEBUI_USER_ID}', 'email': '${WEBUI_USER_EMAIL}', 'role': 'admin',
     'exp': int(time.time()) + 3600, 'iat': int(time.time())},
    '${WEBUI_SECRET_KEY}', algorithm='HS256')
print(token)
")

# ── Helper: upsert a tool or function ─────────────────────────
upsert_component() {
  local type="$1"       # "tools" or "functions"
  local id="$2"
  local name="$3"
  local file="$4"
  local comp_type="$5"  # "filter" for functions, "" for tools
  local description="$6"

  local content
  content=$(cat "${file}")

  # Patch base_url for Docker context
  content=$(echo "${content}" | sed "s|http://localhost:8000|${BROWSER_USE_URL}|g")
  content=$(echo "${content}" | sed "s|http://host.docker.internal:8086|${BROWSER_USE_URL}|g")

  local payload
  if [[ "${type}" == "tools" ]]; then
    payload=$(python3 -c "
import json, sys
print(json.dumps({
    'id': '${id}',
    'name': '${name}',
    'content': sys.stdin.read(),
    'meta': {'description': '${description}'}
}))" <<< "${content}")
  else
    payload=$(python3 -c "
import json, sys
print(json.dumps({
    'id': '${id}',
    'name': '${name}',
    'type': '${comp_type}',
    'content': sys.stdin.read(),
    'meta': {'description': '${description}'}
}))" <<< "${content}")
  fi

  local url="${OPENWEBUI_URL}/api/v1/${type}"

  # Try update first, then create
  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "${url}/id/${id}/update" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${payload}")

  if [[ "${status}" == "200" ]]; then
    printf '  Updated %s/%s\n' "${type}" "${id}"
  else
    status=$(curl -s -o /dev/null -w "%{http_code}" \
      -X POST "${url}/create" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" \
      -d "${payload}")
    printf '  Created %s/%s (HTTP %s)\n' "${type}" "${id}" "${status}"
  fi

  # Activate and make global (for functions only)
  if [[ "${type}" == "functions" ]]; then
    curl -s -o /dev/null -X POST "${url}/id/${id}/toggle" \
      -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json"
    curl -s -o /dev/null -X POST "${url}/id/${id}/toggle/global" \
      -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json"

    # Verify state
    local state
    state=$(curl -s "${url}/id/${id}" -H "Authorization: Bearer ${TOKEN}" \
      | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'active={d.get(\"is_active\")}, global={d.get(\"is_global\")}')")
    printf '  State: %s\n' "${state}"
  fi
}

# ── Register components ───────────────────────────────────────
printf 'Registering browser-use components in OpenWebUI at %s\n\n' "${OPENWEBUI_URL}"

printf 'Tool: Browser Use\n'
upsert_component "tools" "browser_use" \
  "Browser Use - Web Extraction & Image Analysis Tool" \
  "${PROJECT_ROOT}/app/openwebui_tool.py" \
  "" \
  "Fetch web content, detect login walls, process PDFs, and analyze uploaded images."

printf '\nFilter: Vision Image Analyzer\n'
upsert_component "functions" "vision_image_filter" \
  "Vision Image Analyzer" \
  "${PROJECT_ROOT}/app/openwebui_vision_filter.py" \
  "filter" \
  "Analyzes uploaded images via vision LLM with inline clickable references."

printf '\nDone.\n'
