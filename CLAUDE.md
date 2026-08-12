# Elasticstack Ansible Collection

## Fix Workflow

When fixing a bug:

1. Before implementing, identify which molecule scenario covers this code path.
2. If no existing scenario catches the bug, add a verify assertion to the closest
   existing scenario — or extend its converge — rather than creating a new scenario.
   A new scenario is a last resort (each one adds ~10 min to CI).
3. Prefer the lightest test that proves the fix: a config assertion in verify.yml
   beats a full multi-node deployment. Only add nodes/complexity when the bug
   genuinely requires it (e.g. inter-node communication).
4. The test should fail without the fix and pass with it. Confirm this mentally
   or by describing the failure mode before implementing.

## Role default gating

When a role default is commented out (`# foo:`) or has an empty value
(`foo:`, `foo: ""`, `foo: []`, `foo: {}`), the downstream gate must be
an explicit non-empty check, not a bare `is defined`:

```yaml
# Wrong — silently changes behavior when someone uncomments foo:
when: foo is defined

# Right — the empty sentinel behaves the same whether the default is
# commented, missing, or explicitly ""
when: foo | default('') | length > 0
```

The `elasticstack_cert_pass: ""` regression that took several rounds
to diagnose (empty-string propagated into `elasticsearch-keystore add`
stdin and `elasticsearch-certutil --pass`) is the archetypal case.

`scripts/check_argspecs.py` scans role tasks for this pattern and
fails CI when a bare `is defined` gate references a default var whose
declared value is empty or null.
