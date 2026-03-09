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
