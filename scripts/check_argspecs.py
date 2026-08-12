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


def scan_is_defined_gates(repo, empty_default_vars):
    """Flag bare `X is defined` gates in role tasks where X is a default
    var whose declared default is empty or null.

    The problem this catches: a role default like `# foo:` or `foo: ""`
    plus a downstream gate `when: foo is defined` silently changes
    behavior the moment somebody uncomments or explicitly sets the
    empty string — the elasticstack_cert_pass regression. Vars whose
    defaults hold a real value are excluded because the gate is dead
    but harmless.

    A line is considered SAFE when the match sits next to `length`,
    `stdout`, or `content` on the same line — those are already the
    non-empty / register-based forms this scanner wants to encourage.
    """
    hits = []
    for f in sorted(repo.glob("roles/*/tasks/*.yml")):
        try:
            content = f.read_text()
        except OSError:
            continue
        for i, line in enumerate(content.splitlines(), 1):
            for m in IS_DEFINED_RE.finditer(line):
                var = m.group(1)
                if var not in empty_default_vars:
                    continue
                if any(marker in line for marker in ("length", ".stdout", ".content")):
                    continue
                hits.append((f.relative_to(repo), i, var, line.strip()))
    return hits


def main():
    repo = Path(__file__).resolve().parent.parent
    roles = sorted(p for p in (repo / "roles").iterdir() if p.is_dir())
    exit_code = 0
    empty_default_vars = set()

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
        empty_default_vars |= defaults_empty_vars(defaults)
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

    hits = scan_is_defined_gates(repo, empty_default_vars)
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
        for path, line_no, var, snippet in hits:
            print(f"  {path}:{line_no} — {var}: {snippet}", file=sys.stderr)

    if exit_code:
        print(
            "\nFix drift by editing meta/argument_specs.yml or regenerating with "
            "`scripts/gen_argspecs.py <role_path>`.",
            file=sys.stderr,
        )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
