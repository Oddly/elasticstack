#!/usr/bin/env bash
# Check that every molecule scenario is referenced by at least one CI workflow.
# Also checks that every scenario has a verify.yml with assertions.
# Intended to run in CI on PRs that touch molecule/ or .github/workflows/.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKFLOWS_DIR="$REPO_ROOT/.github/workflows"
MOLECULE_DIR="$REPO_ROOT/molecule"
EXIT_CODE=0

# Scenarios that are not standalone tests (utility dirs, shared includes,
# or playbooks invoked directly by ansible-playbook rather than `molecule`)
EXCLUDED_SCENARIOS=(default shared cert_info_module)

workflow_references_scenario() {
    local scenario="$1"
    local line stripped value scenario_indent current_indent
    local in_scenario_matrix=false

    # A scenario is covered only when it is an active item in a `scenario:`
    # matrix or an item in a reusable workflow's `scenarios:` JSON array.
    # Reading files line by line keeps names with spaces safe and stripping
    # comments prevents documentation from counting as executable coverage.
    while IFS= read -r line; do
        stripped="${line%%#*}"

        if [[ "$stripped" =~ ^[[:space:]]*scenarios:[[:space:]]* ]]; then
            value="${stripped#*scenarios:}"
            if [[ "$value" == *"\"${scenario}\""* || "$value" == *"'${scenario}'"* ]]; then
                return 0
            fi
            continue
        fi

        if [[ "$stripped" =~ ^([[:space:]]*)scenario:[[:space:]]*$ ]]; then
            scenario_indent="${#BASH_REMATCH[1]}"
            in_scenario_matrix=true
            continue
        fi

        if [[ "$in_scenario_matrix" == true && "$stripped" =~ ^([[:space:]]*)[^[:space:]-][^:]*: ]]; then
            current_indent="${#BASH_REMATCH[1]}"
            if [ "$current_indent" -le "$scenario_indent" ]; then
                in_scenario_matrix=false
            fi
        fi

        if [[ "$in_scenario_matrix" == true ]]; then
            value="${stripped#"${stripped%%[![:space:]]*}"}"
            value="${value%"${value##*[![:space:]]}"}"
            case "$value" in
                "- ${scenario}"|"- '${scenario}'"|"- \"${scenario}\"")
                    return 0
                    ;;
            esac
        fi
    done < <(
        for workflow in "$WORKFLOWS_DIR"/test_*.yml; do
            [ -f "$workflow" ] || continue
            cat "$workflow"
        done
    )

    return 1
}

echo "=== Molecule scenario CI coverage check ==="
echo

# 1. Check for orphaned scenarios (not referenced by any workflow)
echo "--- Checking for orphaned scenarios ---"
for scenario_dir in "$MOLECULE_DIR"/*/; do
    scenario="$(basename "$scenario_dir")"
    # CI checks the committed checkout; ignore local scenario directories
    # that have not been added to Git yet.
    if ! git -C "$REPO_ROOT" ls-files --error-unmatch -- "molecule/$scenario/molecule.yml" >/dev/null 2>&1; then
        continue
    fi

    # Skip excluded scenarios
    skip=false
    for excluded in "${EXCLUDED_SCENARIOS[@]}"; do
        if [ "$scenario" = "$excluded" ]; then
            skip=true
            break
        fi
    done
    if [[ "$skip" == true ]]; then
        continue
    fi

    # Check if a workflow actively invokes this scenario
    if ! workflow_references_scenario "$scenario"; then
        echo "FAIL: molecule/$scenario is not referenced by any workflow"
        EXIT_CODE=1
    fi
done

if [ "$EXIT_CODE" -eq 0 ]; then
    echo "OK: All scenarios are referenced by at least one workflow"
fi
echo

# 2. Check that every scenario has a verify.yml (except excluded)
echo "--- Checking for missing verify.yml ---"
for scenario_dir in "$MOLECULE_DIR"/*/; do
    scenario="$(basename "$scenario_dir")"
    # Keep the check aligned with the committed checkout.
    if ! git -C "$REPO_ROOT" ls-files --error-unmatch -- "molecule/$scenario/molecule.yml" >/dev/null 2>&1; then
        continue
    fi

    skip=false
    for excluded in "${EXCLUDED_SCENARIOS[@]}"; do
        if [ "$scenario" = "$excluded" ]; then
            skip=true
            break
        fi
    done
    if [[ "$skip" == true ]]; then
        continue
    fi

    if [ ! -f "$scenario_dir/verify.yml" ]; then
        echo "FAIL: molecule/$scenario has no verify.yml"
        EXIT_CODE=1
    fi
done

if [ "$EXIT_CODE" -eq 0 ]; then
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
exit "$EXIT_CODE"
