#!/bin/bash
# Regenerate wiki documentation from ansible-doctor annotations.
# Requires: uv tool install ansible-doctor --with ansible-core
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WIKI_DIR="${REPO_ROOT}/docs/wiki"

for role in elasticsearch kibana logstash beats elasticstack; do
  echo "Generating docs for ${role}..."
  ansible-doctor -f -o "${WIKI_DIR}/Roles-${role}.md" "${REPO_ROOT}/roles/${role}"
done

echo "Done. Role reference pages updated in ${WIKI_DIR}/"
echo "Hand-written pages (Home.md, Architecture.md, Getting-Started.md) are not regenerated."
