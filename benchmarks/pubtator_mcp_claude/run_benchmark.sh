#!/usr/bin/env bash
set -euo pipefail

RUNS="${1:-10}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${ROOT_DIR}/../.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="${ROOT_DIR}/results/${STAMP}"
RUNS_DIR="${OUT_DIR}/runs"
SUMMARY_DIR="${OUT_DIR}/summary"
PUBTATOR_TOOLS="mcp__pubtator-link__pubtator_search_biomedical_entities,mcp__pubtator-link__pubtator_find_entity_relations,mcp__pubtator-link__pubtator_search_literature,mcp__pubtator-link__pubtator_index_review_evidence,mcp__pubtator-link__pubtator_inspect_review_index,mcp__pubtator-link__pubtator_retrieve_review_context_batch,mcp__pubtator-link__pubtator_retrieve_review_context,mcp__pubtator-link__pubtator_get_publication_passages,mcp__pubtator-link__pubtator_estimate_publication_context,mcp__pubtator-link__pubtator_fetch_publication_annotations"

mkdir -p "${RUNS_DIR}" "${SUMMARY_DIR}"
cp "${ROOT_DIR}/clinical_prompt.md" "${OUT_DIR}/clinical_prompt.md"
cp "${ROOT_DIR}/mcp_evaluation_prompt.md" "${OUT_DIR}/mcp_evaluation_prompt.md"
cp "${ROOT_DIR}/judge_prompt.md" "${OUT_DIR}/judge_prompt.md"

printf "run\tclinical_status\tclinical_seconds\tmcp_eval_status\tmcp_eval_seconds\tsession_id\n" > "${SUMMARY_DIR}/runs.tsv"

for i in $(seq 1 "${RUNS}"); do
  run_id="$(printf "run_%02d" "${i}")"
  run_dir="${RUNS_DIR}/${run_id}"
  mkdir -p "${run_dir}"

  docker logs --since 30m pubtator_link_server > "${run_dir}/docker_before.log" 2>&1 || true

  start="$(date +%s)"
  clinical_status=0
  claude --print \
    --disable-slash-commands \
    --allowedTools "${PUBTATOR_TOOLS}" \
    --output-format json \
    --debug-file "${run_dir}/clinical.debug.log" \
    --permission-mode bypassPermissions \
    "$(cat "${ROOT_DIR}/clinical_prompt.md")" \
    > "${run_dir}/clinical_output.json" || clinical_status=$?
  end="$(date +%s)"
  clinical_seconds="$((end - start))"

  session_id=""
  if [[ -s "${run_dir}/clinical_output.json" ]]; then
    session_id="$(jq -r '.session_id // empty' "${run_dir}/clinical_output.json" 2>/dev/null || true)"
  fi

  start="$(date +%s)"
  mcp_status=0
  if [[ -n "${session_id}" ]]; then
    claude --print \
      --resume "${session_id}" \
      --disable-slash-commands \
      --allowedTools "${PUBTATOR_TOOLS}" \
      --output-format json \
      --debug-file "${run_dir}/mcp_evaluation.debug.log" \
      --permission-mode bypassPermissions \
      "$(cat "${ROOT_DIR}/mcp_evaluation_prompt.md")" \
      > "${run_dir}/mcp_evaluation_output.json" || mcp_status=$?
  else
    mcp_status=99
    printf '{"error":"missing session_id; skipped MCP evaluation"}\n' > "${run_dir}/mcp_evaluation_output.json"
  fi
  end="$(date +%s)"
  mcp_seconds="$((end - start))"

  docker logs --since 30m pubtator_link_server > "${run_dir}/docker_after.log" 2>&1 || true
  printf "%s\t%s\t%s\t%s\t%s\t%s\n" "${run_id}" "${clinical_status}" "${clinical_seconds}" "${mcp_status}" "${mcp_seconds}" "${session_id}" >> "${SUMMARY_DIR}/runs.tsv"
done

docker logs --since 4h pubtator_link_server > "${SUMMARY_DIR}/docker_server_last4h.log" 2>&1 || true
docker logs --since 4h pubtator_link_postgres > "${SUMMARY_DIR}/docker_postgres_last4h.log" 2>&1 || true
docker compose -f "${REPO_DIR}/docker/docker-compose.yml" ps > "${SUMMARY_DIR}/docker_compose_ps.txt" 2>&1 || true

{
  printf "# Benchmark Bundle\n\n"
  printf "Benchmark directory: %s\n\n" "${OUT_DIR}"
  printf "## Run Status\n\n"
  cat "${SUMMARY_DIR}/runs.tsv"
  printf "\n\n## Docker Compose\n\n"
  cat "${SUMMARY_DIR}/docker_compose_ps.txt"
  printf "\n\n## Docker Log Summary\n\n"
  printf "server WARN lines: "
  grep -ci "warn\\|warning" "${SUMMARY_DIR}/docker_server_last4h.log" || true
  printf "server ERROR lines: "
  grep -ci "error\\|traceback\\|exception\\|ToolError" "${SUMMARY_DIR}/docker_server_last4h.log" || true
  printf "server HTTP 400 lines: "
  grep -ci "HTTP/1.1 400\\|400 Bad Request\\|HTTP 400" "${SUMMARY_DIR}/docker_server_last4h.log" || true
  printf "postgres ERROR lines: "
  grep -ci "error\\|fatal\\|panic" "${SUMMARY_DIR}/docker_postgres_last4h.log" || true
  printf "\n### Server log notable lines\n\n"
  grep -i "error\\|traceback\\|exception\\|ToolError\\|warn\\|warning\\|HTTP 400\\|400 Bad Request\\|rate limit\\|failed\\|empty" "${SUMMARY_DIR}/docker_server_last4h.log" | tail -n 240 || true

  for run_dir in "${RUNS_DIR}"/run_*; do
    [[ -d "${run_dir}" ]] || continue
    run_id="$(basename "${run_dir}")"
    printf "\n\n# %s\n\n" "${run_id}"
    printf "## Clinical Output\n\n"
    jq -r '.result // .message // tostring' "${run_dir}/clinical_output.json" 2>/dev/null || cat "${run_dir}/clinical_output.json"
    printf "\n\n## MCP Evaluation Output\n\n"
    jq -r '.result // .message // tostring' "${run_dir}/mcp_evaluation_output.json" 2>/dev/null || cat "${run_dir}/mcp_evaluation_output.json"
    printf "\n\n## Claude Debug Summary\n\n"
    printf "clinical WARN lines: "
    grep -ci "warn\\|warning\\|stall" "${run_dir}/clinical.debug.log" || true
    printf "clinical MCP tool calls:\n"
    grep "Calling MCP tool" "${run_dir}/clinical.debug.log" | sed 's/^/- /' || true
    printf "clinical failures:\n"
    grep -i "error\\|failed\\|ToolError\\|HTTP 400\\|400 Bad Request" "${run_dir}/clinical.debug.log" | tail -n 80 | sed 's/^/- /' || true
    printf "mcp-eval WARN lines: "
    grep -ci "warn\\|warning\\|stall" "${run_dir}/mcp_evaluation.debug.log" || true
    printf "mcp-eval failures:\n"
    grep -i "error\\|failed\\|ToolError\\|HTTP 400\\|400 Bad Request" "${run_dir}/mcp_evaluation.debug.log" | tail -n 80 | sed 's/^/- /' || true
  done
} > "${SUMMARY_DIR}/judge_input.md"

claude --print \
  --disable-slash-commands \
  --tools "" \
  --output-format json \
  --debug-file "${SUMMARY_DIR}/judge.debug.log" \
  --permission-mode bypassPermissions \
  "$(cat "${ROOT_DIR}/judge_prompt.md")

Below is the compact benchmark evidence bundle.

$(cat "${SUMMARY_DIR}/judge_input.md")" \
  > "${SUMMARY_DIR}/judge_output.json"

printf "%s\n" "${OUT_DIR}" > "${ROOT_DIR}/latest_result_dir.txt"
printf "Benchmark complete: %s\n" "${OUT_DIR}"
