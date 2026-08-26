#!/usr/bin/env bash
# End-to-end check against a running API. Exits non-zero on the first failure so
# it's usable in CI as well as by hand.
set -euo pipefail
API="${API:-http://localhost:8000}"

step() { printf '\n\033[1m%s\033[0m\n' "$1"; }

step "health"
curl -fsS "$API/api/health" | python3 -m json.tool | head -25

step "create session"
SID=$(curl -fsS -X POST "$API/api/sessions" -H 'content-type: application/json' \
      -d '{"title":"smoke"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
echo "session $SID"

step "grounded answer"
curl -fsS -X POST "$API/api/chat" -H 'content-type: application/json' \
  -d "{\"session_id\":\"$SID\",\"message\":\"What is founder mode?\"}" \
  | python3 -c '
import sys, json
b = json.load(sys.stdin)
g = b.get("grounding") or {}
print("route      ", b["route"], "via", b["decided_by"])
print("provider   ", b["provider"], b["model"])
print("citations  ", len(b["citations"]))
print("grounding  ", g.get("supported"), "/", g.get("total_claims"), "claims supported")
print("timings    ", b["timings"])
print()
print(b["text"][:400])
'

step "artifact + sanitiser"
curl -fsS -X POST "$API/api/chat" -H 'content-type: application/json' \
  -d "{\"session_id\":\"$SID\",\"message\":\"make me an HTML one-pager on growth loops\"}" \
  | python3 -c '
import sys, json
b = json.load(sys.stdin)
a = b.get("artifact") or {}
r = a.get("sanitizer_report", {})
print("artifact   ", a.get("kind"), "-", a.get("title"))
print("blocked    ", r.get("blocked_count"))
print("CSP present", "Content-Security-Policy" in a.get("content",""))
'

step "session isolation"
curl -fsS "$API/api/sessions/$SID/messages" \
  | python3 -c 'import sys,json;print(len(json.load(sys.stdin)),"messages in this session")'

step "traces"
curl -fsS "$API/api/admin/traces?limit=3" | python3 -m json.tool | head -20

printf '\n\033[32msmoke passed\033[0m\n'
