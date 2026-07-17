#!/usr/bin/env bash
# End-to-end demo against a RUNNING server (curl). Assumes uvicorn is up:
#   uvicorn app.main:app --port 8000
# and .env has GROQ_API_KEY (and optionally MONGODB_URI).
#
# Flow: ingest v1 -> browse sections -> search -> create selection ->
#        generate (real Groq) -> retrieve (fresh) -> ingest v2 ->
#        retrieve the SAME generation (stale + diff) -> list by selection.
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:8000}"
DATA_DIR="$(dirname "$0")/../data"

echo "== 1. Ingest v1 =="
curl -s -X POST "$BASE/documents/ingest" -H 'Content-Type: application/json' \
  -d "{\"slug\":\"ct200-manual\",\"title\":\"CT-200 Manual\",\"file_path\":\"$DATA_DIR/ct200_manual.md\"}"
echo

echo "== 2. Browse top-level sections (v1) =="
curl -s "$BASE/documents/ct200-manual/sections?version=1" | python -m json.tool

echo "== 3. Search 'bpm' =="
curl -s "$BASE/nodes/search?q=bpm&document_id=1&version=1" | python -m json.tool

SAFETY_ID=$(curl -s "$BASE/documents/ct200-manual/sections?version=1" \
  | python -c "import sys,json;print([s for s in json.load(sys.stdin) if s['heading_text']=='Safety Limits'][0]['node_id'])")
echo "Safety Limits node id: $SAFETY_ID"

echo "== 4. Create selection pinned to v1 =="
SEL=$(curl -s -X POST "$BASE/selections" -H 'Content-Type: application/json' \
  -d "{\"name\":\"safety\",\"node_ids\":[$SAFETY_ID],\"version\":1}")
echo "$SEL" | python -m json.tool
SEL_ID=$(echo "$SEL" | python -c "import sys,json;print(json.load(sys.stdin)['id'])")

echo "== 5. Generate test cases (real Groq) =="
curl -s -X POST "$BASE/selections/$SEL_ID/generate" | python -m json.tool
GEN_ID=$(curl -s "$BASE/generations?selection_id=$SEL_ID" | python -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")

echo "== 6. Retrieve generation BEFORE re-ingest (fresh) =="
curl -s "$BASE/generations/$GEN_ID" | python -m json.tool

echo "== 7. Ingest v2 (Safety Limits: 160->140 bpm, 5->7 kg) =="
curl -s -X POST "$BASE/documents/ingest" -H 'Content-Type: application/json' \
  -d "{\"slug\":\"ct200-manual\",\"title\":\"CT-200 Manual\",\"file_path\":\"$DATA_DIR/ct200_manual_v2.md\"}"
echo

echo "== 8. Retrieve the SAME generation AFTER re-ingest (stale + diff) =="
curl -s "$BASE/generations/$GEN_ID" | python -m json.tool

echo "== 9. List by selection (staleness inlined) =="
curl -s "$BASE/generations?selection_id=$SEL_ID" | python -m json.tool