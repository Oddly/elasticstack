#!/usr/bin/env python3
"""
Generate meta/argument_specs.yml for an Ansible role by parsing @var
docblocks in defaults/main.yml.

Usage:  gen_argspecs.py <role_path>
Writes: <role_path>/meta/argument_specs.yml
"""
import sys
import re
import yaml
from pathlib import Path


def parse_defaults(path):
    """Returns list of dicts: [{'name': str, 'description': str, 'default': any}]"""
    with open(path) as f:
        text = f.read()
    lines = text.splitlines()
    entries = []
    i = 0
    pending_desc = None
    pending_var = None
    while i < len(lines):
        line = lines[i]

        # Single-line @var: `# @var NAME:description: TEXT`
        m = re.match(r"^# @var\s+([\w.]+):description:\s*(.*)$", line)
        if m and not m.group(2).endswith('>'):
            pending_var = m.group(1)
            pending_desc = m.group(2).strip()
            i += 1
            continue

        # Multi-line @var: `# @var NAME:description: >`  then lines until `# @end`
        # OR the first non-comment line (some docblocks in this repo omit @end).
        m = re.match(r"^# @var\s+([\w.]+):description:\s*>\s*$", line)
        if m:
            pending_var = m.group(1)
            desc_lines = []
            i += 1
            while i < len(lines):
                stripped = lines[i].strip()
                if stripped.startswith("# @end"):
                    i += 1
                    break
                if stripped.startswith("# @var"):
                    # A new @var starts (typically an :example: sibling) —
                    # description ends here, leave i pointing at that line.
                    break
                if not stripped.startswith("#"):
                    # Docblock ended without @end — leave i pointing at
                    # the value line and let the value-line branch handle it.
                    break
                desc_lines.append(lines[i].lstrip("# ").rstrip())
                i += 1
            pending_desc = " ".join(l for l in desc_lines if l).strip()
            continue

        # Also skip `# @var ...:example:` blocks
        if re.match(r"^# @var\s+[\w.]+:example:", line):
            # skip the example block similarly
            if line.rstrip().endswith('>'):
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("# @end"):
                    i += 1
                if i < len(lines):
                    i += 1
            else:
                i += 1
            continue

        # Value line: NAME: VALUE (or NAME: on its own for multi-line YAML)
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if m and pending_var == m.group(1):
            varname = m.group(1)
            # Try to YAML-parse the full block (may span lines for lists/dicts)
            # Simple heuristic: take from here until next blank line or next @var
            block_end = i + 1
            while block_end < len(lines):
                nxt = lines[block_end]
                if (
                    nxt.strip() == ""
                    or nxt.startswith("# @var")
                    or nxt.startswith("# ==")
                ):
                    break
                block_end += 1
            block_text = "\n".join(lines[i:block_end])
            try:
                parsed = yaml.safe_load(block_text)
                if isinstance(parsed, dict) and varname in parsed:
                    default_val = parsed[varname]
                else:
                    default_val = None
            except Exception:
                default_val = None
            entries.append(
                {"name": varname, "description": pending_desc or "", "default": default_val}
            )
            pending_var = None
            pending_desc = None
            i = block_end
            continue

        # Also handle: commented-out defaults (# varname:) — skip but record with unset default
        m = re.match(r"^#\s*(\w+):\s*$", line)
        if m and pending_var == m.group(1):
            entries.append(
                {"name": m.group(1), "description": pending_desc or "", "default": None}
            )
            pending_var = None
            pending_desc = None
            i += 1
            continue

        i += 1
    return entries


def infer_type(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, str):
        # Jinja-templated strings still get type str
        return "str"
    return "str"


def build_argument_specs(role_name, entries, short_desc, long_desc):
    options = {}
    for e in entries:
        opt = {"description": e["description"] or f"See defaults/main.yml for {e['name']}."}
        if e["default"] is not None:
            opt["type"] = infer_type(e["default"])
            opt["default"] = e["default"]
        else:
            opt["type"] = "raw"
        options[e["name"]] = opt
    return {
        "argument_specs": {
            "main": {
                "short_description": short_desc,
                "description": long_desc,
                "options": options,
            }
        }
    }


ROLE_METADATA = {
    "elasticsearch": (
        "Install, configure, and manage Elasticsearch",
        "Handles cluster formation, TLS certificate management, security setup (users, passwords, HTTPS), rolling upgrades (8.x to 9.x), JVM tuning, and systemd service management.",
    ),
    "kibana": (
        "Install, configure, and manage Kibana",
        "Handles package install, TLS setup for the Kibana web UI, keystore-managed secrets, integration with an Elasticsearch backend, and systemd service management.",
    ),
    "logstash": (
        "Install, configure, and manage Logstash",
        "Handles package install, pipeline configuration, TLS certificate management for input/output, JVM tuning, and systemd service management.",
    ),
    "beats": (
        "Install, configure, and manage Elastic Beats (filebeat, metricbeat, auditbeat)",
        "Handles package install, ECS-schema output configuration to Elasticsearch or Logstash, TLS certificate distribution, and systemd service management per beat.",
    ),
    "elasticstack": (
        "Shared defaults and CA management for the oddly.elasticstack collection",
        "Provides collection-wide variables (inventory group names, ports, CA host, certificate settings) and the internal certificate authority workflow used by the elasticsearch, kibana, logstash, and beats roles.",
    ),
    "repos": (
        "Manage Elastic package repositories",
        "Installs the Elastic apt/yum repository configuration matching elasticstack_release and elasticstack_repo_base_url, keeping the elasticsearch/kibana/logstash/beats package installs pointed at the right major version.",
    ),
}


def main():
    role_path = Path(sys.argv[1]).resolve()
    role_name = role_path.name
    defaults = role_path / "defaults" / "main.yml"
    if not defaults.exists():
        print(f"no defaults/main.yml at {defaults}", file=sys.stderr)
        sys.exit(1)

    entries = parse_defaults(defaults)
    short_desc, long_desc = ROLE_METADATA.get(
        role_name, (f"Role {role_name}", f"Role {role_name}.")
    )
    spec = build_argument_specs(role_name, entries, short_desc, long_desc)

    (role_path / "meta").mkdir(exist_ok=True)
    outpath = role_path / "meta" / "argument_specs.yml"
    with open(outpath, "w") as f:
        f.write("---\n")
        yaml.dump(spec, f, sort_keys=False, default_flow_style=False, width=120)
    print(f"wrote {outpath} with {len(entries)} options")


if __name__ == "__main__":
    main()
