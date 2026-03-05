# oddly.elasticstack

An Ansible collection for deploying and managing the Elastic Stack (Elasticsearch, Kibana, Logstash, and Beats) on Debian, Ubuntu, and RHEL/Rocky Linux systems. Forked from the NETWAYS collection and extended with Elastic 9.x support, rolling upgrades, and full TLS certificate lifecycle management.

## What this collection does

The collection handles the complete lifecycle of an Elastic Stack deployment: package repository setup, installation, configuration, TLS certificate generation and renewal, security initialization (users, roles, passwords), service management, and rolling upgrades from 8.x to 9.x. It works both for standalone single-service installs and for coordinated multi-node full-stack deployments where roles auto-discover each other through inventory groups.

## Roles

| Role | Purpose |
|------|---------|
| [elasticstack](roles/elasticstack.md) | Shared defaults used by all other roles (ports, group names, CA settings, repository URLs) |
| [elasticsearch](roles/elasticsearch.md) | Elasticsearch nodes — cluster formation, JVM tuning, security setup, rolling upgrades |
| [kibana](roles/kibana.md) | Kibana — web UI, Elasticsearch connection, optional HTTPS frontend |
| [logstash](roles/logstash.md) | Logstash — pipeline management (inputs, filters, outputs), queue config, ES user/role creation |
| [beats](roles/beats.md) | Filebeat, Metricbeat, and Auditbeat — log/metric/audit collection with syslog, journald, and Docker inputs |
| [repos](roles/repos.md) | APT/YUM repository setup, GPG key management |

## Quick start

```yaml
# requirements.yml
collections:
  - name: oddly.elasticstack

# inventory.yml
all:
  children:
    elasticsearch:
      hosts:
        es1: { ansible_host: 192.168.1.10 }
        es2: { ansible_host: 192.168.1.11 }
        es3: { ansible_host: 192.168.1.12 }
    kibana:
      hosts:
        kb1: { ansible_host: 192.168.1.20 }
    logstash:
      hosts:
        ls1: { ansible_host: 192.168.1.30 }

# playbook.yml
- hosts: all
  vars:
    elasticstack_release: 9
    elasticstack_full_stack: true
  roles:
    - oddly.elasticstack.repos
    - oddly.elasticstack.elasticsearch
    - oddly.elasticstack.kibana
    - oddly.elasticstack.logstash
    - oddly.elasticstack.beats
```

See the [Getting Started](getting-started.md) guide for a full walkthrough, or the [Architecture](architecture.md) page for how the roles interact.

## Supported platforms

- Debian 11 (Bullseye), 12 (Bookworm), 13 (Trixie)
- Ubuntu 22.04 (Jammy), 24.04 (Noble)
- Rocky Linux / RHEL 8, 9, 10
- Ansible 2.18+
- Elastic Stack 8.x and 9.x
