<div align="center">
  <img src="docs/elastic-logo.svg" alt="Elastic Stack" width="120">
  <p><strong>oddly.elasticstack</strong></p>
  <p>
    Deploy and manage the Elastic Stack with Ansible.<br>
    Elasticsearch, Kibana, Logstash, and Beats — from repos to rolling upgrades.
  </p>
  <p>
    <a href="https://github.com/Oddly/elasticstack/actions/workflows/test_full_stack.yml"><img src="https://github.com/Oddly/elasticstack/actions/workflows/test_full_stack.yml/badge.svg" alt="Full Stack Tests"></a>
    <a href="https://github.com/Oddly/elasticstack/actions/workflows/test_elasticsearch_modules.yml"><img src="https://github.com/Oddly/elasticstack/actions/workflows/test_elasticsearch_modules.yml/badge.svg" alt="ES Module Tests"></a>
    <a href="https://github.com/Oddly/elasticstack/actions/workflows/test_linting.yml"><img src="https://github.com/Oddly/elasticstack/actions/workflows/test_linting.yml/badge.svg" alt="Linting"></a>
    <a href="https://github.com/Oddly/elasticstack/wiki"><img src="https://img.shields.io/badge/docs-wiki-blue" alt="Documentation"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-green" alt="License"></a>
  </p>
  <p>
    <a href="https://github.com/Oddly/elasticstack/wiki/Getting-Started">Getting started</a> &middot;
    <a href="https://github.com/Oddly/elasticstack/wiki/Architecture">Architecture</a> &middot;
    <a href="https://github.com/Oddly/elasticstack/wiki">Documentation</a> &middot;
    <a href="https://github.com/Oddly/elasticstack/issues">Issues</a>
  </p>
</div>

---

> **This collection is under active development.** APIs, default values, and variable names may change between releases without deprecation notices. Pin to a specific version in your `requirements.yml` if you need stability.

---

## Overview

An Ansible collection that handles the complete lifecycle of an Elastic Stack deployment: package repositories, installation, cluster formation, TLS certificate generation and renewal, security initialization, service management, and rolling upgrades from 8.x to 9.x.

It works both for standalone single-service installs and for coordinated multi-node deployments where roles auto-discover each other through inventory groups.

Forked from [NETWAYS/ansible-collection-elasticstack](https://github.com/NETWAYS/ansible-collection-elasticstack).

## Features

- **Elastic 8.x and 9.x** with automatic version-specific configuration
- **Rolling upgrades** from 8.x to 9.x, one node at a time with shard allocation management
- **Full TLS PKI** — CA generation, per-node certificates, automatic renewal before expiry
- **Custom TLS certificates** — bring your own certs (PEM or P12) from any CA, with format auto-detection, separate transport/HTTP certs on ES, and built-in expiry warnings
- **Security initialization** — bootstrap passwords, keystore management, user/role creation
- **Multi-node orchestration** — roles discover each other through inventory groups
- **Beats collection** — Filebeat (log, syslog TCP/UDP, journald, Docker), Metricbeat, Auditbeat

## Quickstart

```bash
ansible-galaxy collection install oddly.elasticstack
```

```yaml
# inventory.yml
all:
  children:
    elasticsearch:
      hosts:
        es1: { ansible_host: 10.0.1.10 }
        es2: { ansible_host: 10.0.1.11 }
        es3: { ansible_host: 10.0.1.12 }
    kibana:
      hosts:
        kb1: { ansible_host: 10.0.1.20 }
    logstash:
      hosts:
        ls1: { ansible_host: 10.0.1.30 }
```

```yaml
# playbook.yml
- hosts: all
  vars:
    elasticstack_release: 9
  roles:
    - oddly.elasticstack.repos
    - oddly.elasticstack.elasticsearch
    - oddly.elasticstack.kibana
    - oddly.elasticstack.logstash
    - oddly.elasticstack.beats
```

Roles run in order. Each one uses inventory group names to find the other services. After the run, initial passwords are in `/usr/share/elasticsearch/initial_passwords` on the first ES host.

See the **[getting started guide](https://github.com/Oddly/elasticstack/wiki/Getting-Started)** for single-node setups, disabling security, package mirrors, and more.

## Roles

| Role | Purpose |
|------|---------|
| [`repos`](https://github.com/Oddly/elasticstack/wiki/Roles-repos) | APT/YUM repository and GPG key setup |
| [`elasticsearch`](https://github.com/Oddly/elasticstack/wiki/Roles-elasticsearch) | Cluster formation, JVM tuning, security setup, rolling upgrades |
| [`kibana`](https://github.com/Oddly/elasticstack/wiki/Roles-kibana) | Web UI, Elasticsearch connection, optional HTTPS frontend |
| [`logstash`](https://github.com/Oddly/elasticstack/wiki/Roles-logstash) | Pipeline management, queue config, ES user/role creation |
| [`beats`](https://github.com/Oddly/elasticstack/wiki/Roles-beats) | Filebeat, Metricbeat, Auditbeat with syslog, journald, Docker inputs |
| [`elasticstack`](https://github.com/Oddly/elasticstack/wiki/Roles-elasticstack) | Shared defaults inherited by all roles (ports, groups, CA, repos) |

## Supported platforms

| | Versions |
|-|----------|
| Debian | 11, 12, 13 |
| Ubuntu | 22.04, 24.04 |
| Rocky Linux / RHEL | 8, 9, 10 |
| Elastic Stack | 8.x, 9.x |
| Ansible | 2.18+ |

## Documentation

Full documentation lives in the **[wiki](https://github.com/Oddly/elasticstack/wiki)**:

- **[Getting started](https://github.com/Oddly/elasticstack/wiki/Getting-Started)** — single-node and multi-node walkthroughs
- **[Architecture](https://github.com/Oddly/elasticstack/wiki/Architecture)** — data flow, TLS PKI, security init, rolling upgrades, retry budgets, container workarounds
- **Role reference** — every variable, operational note, and task flow diagram for each role

## Contributing

Issues and pull requests welcome. Branch naming: `fix/` for bug fixes, `feature/` for enhancements, `doc/` for documentation changes.

## License

[GPL-3.0-or-later](LICENSE)
