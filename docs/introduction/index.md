# Introduction

oddly.elasticstack is an Ansible collection for deploying and managing the Elastic Stack on Debian, Ubuntu, and RHEL/Rocky Linux systems. It handles the complete lifecycle: package repositories, installation, TLS certificate generation, security initialization, service management, and rolling upgrades from 8.x to 9.x.

## What this collection does

The collection provides six roles that cover each layer of the stack. They work both independently (install just Elasticsearch, or just Beats) and as a coordinated full-stack deployment where roles auto-discover each other through inventory groups.

| Role | Purpose |
|------|---------|
| [**repos**](../reference/repos.md) | APT/YUM repository and GPG key setup |
| [**elasticsearch**](../reference/elasticsearch.md) | Cluster formation, JVM tuning, security, rolling upgrades |
| [**kibana**](../reference/kibana.md) | Web UI, Elasticsearch connection, optional HTTPS |
| [**logstash**](../reference/logstash.md) | Pipeline management, queue config, ES user/role creation |
| [**beats**](../reference/beats.md) | Filebeat, Metricbeat, Auditbeat collection agents |
| [**elasticstack**](../reference/elasticstack.md) | Shared defaults inherited by all roles |

## Supported platforms

| Category | Versions |
|----------|----------|
| Debian | 12 (Bookworm), 13 (Trixie) |
| Ubuntu | 22.04 (Jammy), 24.04 (Noble), 26.04 (Resolute) |
| Rocky Linux / RHEL | 9, 10 |
| Elastic Stack | 8.x, 9.x |
| Ansible | 2.18+ |

## Next steps

- [Getting Started](getting-started.md) walks you through installing the collection and deploying your first cluster.
- [Architecture](../guide/architecture.md) explains how the roles interact, how TLS is managed, and how security bootstrapping works.
