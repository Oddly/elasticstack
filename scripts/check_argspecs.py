#!/usr/bin/env python3
"""
Verify that every role's meta/argument_specs.yml lists the same variables
its defaults/main.yml defines. Fails CI when the two drift.

Runs across every role that has a meta/argument_specs.yml. Roles without
one (e.g. `repos`, which uses variables from `elasticstack` instead) are
skipped intentionally.

Exit codes:
  0  All roles in sync
  1  At least one role has drift (details on stderr)
  2  Usage / setup error

The parser only looks at the top-level `varname: value` lines in
defaults/main.yml. Internal-only vars (leading underscore) are ignored
so vars/main.yml-style facts don't need arg-spec entries.
"""
import sys
import re
from pathlib import Path

try:
    import yaml
except ImportError:
    print("check_argspecs: PyYAML is required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)


VAR_LINE = re.compile(r"^([A-Za-z][\w]*)\s*:")


def defaults_vars(path):
    """Top-level variable names in a defaults/main.yml, minus internal underscore vars."""
    out = set()
    with open(path) as f:
        for line in f:
            m = VAR_LINE.match(line)
            if m:
                name = m.group(1)
                if not name.startswith("_"):
                    out.add(name)
    return out


def defaults_empty_vars(path):
    """Names whose value in defaults/main.yml is empty or null.

    An entry that looks like `foo:` (nothing after the colon) or
    `foo: ""` / `foo: []` / `foo: {}` / `foo: null` counts as empty.
    Those are the ones where `is defined` in downstream gates silently
    changes meaning the moment somebody supplies an empty string —
    which is exactly the elasticstack_cert_pass regression class.
    """
    out = set()
    empty_val = re.compile(
        r"""^([a-z][\w]*)\s*:\s*
            (?:                       # then either:
                (?:\#.*)?             # trailing comment only
                |""                   # empty string
                |''
                |\[\s*\]              # empty list
                |\{\s*\}              # empty dict
                |[Nn]ull
                |~
            )?\s*(?:\#.*)?$""",
        re.VERBOSE,
    )
    with open(path) as f:
        for line in f:
            m = empty_val.match(line)
            if m:
                out.add(m.group(1))
    return out


def argspec_options(path):
    """Option names declared under the role's `main` entry point.

    Task-file entry points (e.g. node_maintenance_start / _end) are
    invoked with per-call parameters that don't need to appear in
    defaults/main.yml — they're inputs to a specific action, not
    role-wide defaults. Only `main`'s options are role-wide vars.
    """
    with open(path) as f:
        spec = yaml.safe_load(f) or {}
    entries = spec.get("argument_specs") or {}
    main = entries.get("main") or {}
    return set((main.get("options") or {}).keys())


IS_DEFINED_RE = re.compile(r"\b([a-z][\w]*)\s+is\s+defined\b")


def _paired_guard_for(var, expr):
    """Return True iff `expr` also contains a same-var guard for `var`
    that establishes non-emptiness or register-shape existence.

    Guards recognised (all with `var` as the target, no other names):

      - `var | ... | length ...`  (any filter chain that ends in `length`)
      - `var.stdout` / `var.content`  (register reference)
      - `var | ... | bool`  (truthy check — `""` is falsey)

    The check is targeted at `var` specifically. An unrelated
    `other.stdout` or `other | length` in the same expression does NOT
    excuse a bare `var is defined`.
    """
    var_re = re.escape(var)
    # `var` followed by any pipe-chain that ultimately reaches `length`
    # or `bool` — matches `var | length`, `var | string | length > 0`,
    # `var | default('') | length > 0`, `var | bool`, etc. Intermediate
    # filters can be `name(args)` or bare names.
    filter_chain = r"(?:\s*\|\s*\w+(?:\([^)]*\))?)*"
    patterns = (
        rf"\b{var_re}{filter_chain}\s*\|\s*length\b",
        rf"\b{var_re}{filter_chain}\s*\|\s*bool\b",
        rf"\b{var_re}\.(?:stdout|content)\b",
    )
    return any(re.search(p, expr) for p in patterns)


def _flatten_when(when):
    """Ansible's `when` is either a string, a list of strings, or a
    boolean. Yield each condition-string; ignore booleans."""
    if isinstance(when, str):
        yield when
    elif isinstance(when, list):
        for item in when:
            if isinstance(item, str):
                yield item
    # bool / None / dict → nothing to check


def _walk_tasks(items, path, empties_for_role, hits):
    """Recurse through a task list, inspecting each task's `when:`
    (and any nested block/rescue/always children)."""
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", ""))
        for cond in _flatten_when(item.get("when")):
            for m in IS_DEFINED_RE.finditer(cond):
                var = m.group(1)
                if var not in empties_for_role:
                    continue
                if _paired_guard_for(var, cond):
                    continue
                hits.append((path, name, var, cond.strip()))

        for sub_key in ("block", "rescue", "always"):
            if sub_key in item:
                _walk_tasks(item[sub_key], path, empties_for_role, hits)


def scan_is_defined_gates(repo, empty_default_vars_by_role):
    """Flag bare `X is defined` gates in role tasks where X is a
    same-role default var whose declared value is empty or null.

    Task YAML is parsed and only `when:` expressions are inspected so
    comments and task names never trigger a false positive. The empty
    defaults set is scoped per role so an empty `foo` in role A does
    not falsely flag `foo is defined` in role B (where `foo` may hold
    a real default). A `X is defined` is exempted only when the same
    condition also contains a same-var non-empty guard
    (`X | length …`, `X | bool`, `X.stdout`, `X.content`, or
    `X | default(...) | length …`).
    """
    hits = []
    for role_dir in sorted((repo / "roles").iterdir()):
        if not role_dir.is_dir():
            continue
        empties = empty_default_vars_by_role.get(role_dir.name, set())
        if not empties:
            continue
        for task_file in sorted((role_dir / "tasks").rglob("*.yml")):
            try:
                loaded = yaml.safe_load(task_file.read_text()) or []
            except (OSError, yaml.YAMLError):
                continue
            _walk_tasks(loaded, task_file.relative_to(repo), empties, hits)
    return hits


def main():
    repo = Path(__file__).resolve().parent.parent
    roles = sorted(p for p in (repo / "roles").iterdir() if p.is_dir())
    exit_code = 0
    empty_default_vars_by_role = {}

    for role in roles:
        defaults = role / "defaults" / "main.yml"
        specs = role / "meta" / "argument_specs.yml"
        if not specs.exists():
            continue  # role opts out
        if not defaults.exists():
            print(
                f"[{role.name}] has meta/argument_specs.yml but no defaults/main.yml",
                file=sys.stderr,
            )
            exit_code = 1
            continue

        vars_ = defaults_vars(defaults)
        empty_default_vars_by_role[role.name] = defaults_empty_vars(defaults)
        opts = argspec_options(specs)
        missing_in_spec = vars_ - opts
        extra_in_spec = opts - vars_

        if missing_in_spec or extra_in_spec:
            exit_code = 1
            print(f"\n[{role.name}] argument_specs drift:", file=sys.stderr)
            for v in sorted(missing_in_spec):
                print(f"  - in defaults but missing from spec: {v}", file=sys.stderr)
            for v in sorted(extra_in_spec):
                print(f"  - in spec but no longer in defaults: {v}", file=sys.stderr)
        else:
            print(f"[{role.name}] ok ({len(vars_)} vars)")

    hits = scan_is_defined_gates(repo, empty_default_vars_by_role)
    if hits:
        exit_code = 1
        print("\nBare `X is defined` gates on role default vars:", file=sys.stderr)
        print(
            "These silently change behavior when the default is uncommented "
            "or set to an empty value (see the elasticstack_cert_pass regression "
            "for the pattern this catches). Rewrite the gate to check for "
            "non-empty explicitly, e.g. `X | default('') | length > 0`.",
            file=sys.stderr,
        )
        for path, task_name, var, cond in hits:
            label = task_name or "(unnamed task)"
            print(f"  {path} — {label}: `{cond}` (var: {var})", file=sys.stderr)

    if exit_code:
        print(
            "\nFix drift by editing meta/argument_specs.yml or regenerating with "
            "`scripts/gen_argspecs.py <role_path>`.",
            file=sys.stderr,
        )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
