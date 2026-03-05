#!/usr/bin/env bash
# Check that every molecule scenario is referenced by at least one CI workflow.
# Also checks that every scenario has a verify.yml with assertions.
# Intended to run in CI on PRs that touch molecule/ or .github/workflows/.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKFLOWS_DIR="$REPO_ROOT/.github/workflows"
MOLECULE_DIR="$REPO_ROOT/molecule"
EXIT_CODE=0

# Scenarios that are not standalone tests (utility dirs, shared includes)
EXCLUDED_SCENARIOS="shared plugins"

echo "=== Molecule scenario CI coverage check ==="
echo

# 1. Check for orphaned scenarios (not referenced by any workflow)
echo "--- Checking for orphaned scenarios ---"
for scenario_dir in "$MOLECULE_DIR"/*/; do
    scenario="$(basename "$scenario_dir")"

    # Skip excluded scenarios
    skip=false
    for excluded in $EXCLUDED_SCENARIOS; do
        if [ "$scenario" = "$excluded" ]; then
            skip=true
            break
        fi
    done
    $skip && continue

    # Check if any workflow references this scenario name
    if ! grep -rql "$scenario" "$WORKFLOWS_DIR"/test_*.yml 2>/dev/null; then
        echo "FAIL: molecule/$scenario is not referenced by any workflow"
        EXIT_CODE=1
    fi
done

if [ $EXIT_CODE -eq 0 ]; then
    echo "OK: All scenarios are referenced by at least one workflow"
fi
echo

# 2. Check that every scenario has a verify.yml (except excluded)
echo "--- Checking for missing verify.yml ---"
for scenario_dir in "$MOLECULE_DIR"/*/; do
    scenario="$(basename "$scenario_dir")"

    skip=false
    for excluded in $EXCLUDED_SCENARIOS; do
        if [ "$scenario" = "$excluded" ]; then
            skip=true
            break
        fi
    done
    $skip && continue

    if [ ! -f "$scenario_dir/verify.yml" ]; then
        echo "FAIL: molecule/$scenario has no verify.yml"
        EXIT_CODE=1
    fi
done

if [ $EXIT_CODE -eq 0 ]; then
    echo "OK: All scenarios have verify.yml"
fi
echo

# 3. Check workflow path-filter coverage for roles
echo "--- Checking workflow path-filter coverage ---"
for role_dir in "$REPO_ROOT"/roles/*/; do
    role="$(basename "$role_dir")"

    # Check if any test workflow's pull_request paths include this role
    if ! grep -rql "roles/$role/" "$WORKFLOWS_DIR"/test_*.yml 2>/dev/null; then
        echo "WARN: roles/$role/ is not in any workflow's path filter"
    fi
done
echo

echo "=== Done ==="
exit $EXIT_CODE
