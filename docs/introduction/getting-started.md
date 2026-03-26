# Getting Started

## Prerequisites

- Ansible 2.18 or later
- Target hosts running Debian 11/12/13, Ubuntu 22.04/24.04, or Rocky Linux/RHEL 8/9/10
- SSH access to target hosts with root or sudo privileges
- Minimum 4 GB RAM per Elasticsearch node (8 GB recommended)
- Python 3 on all target hosts (with `python3-apt` on Debian/Ubuntu)

## Install the collection

```bash
ansible-galaxy collection install oddly.elasticstack
```

Or add to your `requirements.yml`:

```yaml
collections:
  - name: oddly.elasticstack
```

!!! note
    The default `elasticstack_release` is `8`. All examples below explicitly set it to `9` for new deployments. If you omit it, the collection installs Elastic 8.x packages.

## Single-node deployment (simplest)

This deploys everything on one host — useful for development and testing.

**inventory.yml:**

```yaml
all:
  children:
    elasticsearch:
      hosts:
        elastic1:
          ansible_host: 192.168.1.10
```

**playbook.yml:**

```yaml
- hosts: all
  vars:
    elasticstack_release: 9
    elasticstack_full_stack: false
    elasticsearch_heap: 2
  roles:
    - oddly.elasticstack.repos
    - oddly.elasticstack.elasticsearch
```

```bash
ansible-playbook -i inventory.yml playbook.yml
```

After the run completes, Elasticsearch will be listening on `https://localhost:9200` with security enabled. The `elastic` superuser password and all built-in user passwords are stored in `/usr/share/elasticsearch/initial_passwords` on the host. You can retrieve the `elastic` password with:

```bash
grep "PASSWORD elastic" /usr/share/elasticsearch/initial_passwords | awk '{print $4}'
```

In multi-node deployments, this file lives on the CA host (the first node in the `elasticsearch` group) and other roles fetch passwords from it automatically via `delegate_to`.

## Multi-node full-stack deployment

**inventory.yml:**

```yaml
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
    beats:
      hosts:
        app1: { ansible_host: 10.0.1.40 }
        app2: { ansible_host: 10.0.1.41 }
```

**group_vars/all.yml:**

```yaml
elasticstack_release: 9
elasticstack_full_stack: true
elasticstack_security: true
```

**playbook.yml:**

```yaml
- hosts: all
  roles:
    - oddly.elasticstack.repos
    - oddly.elasticstack.elasticsearch
    - oddly.elasticstack.kibana
    - oddly.elasticstack.logstash
    - oddly.elasticstack.beats
```

Each role only acts on hosts in its matching group. Elasticsearch nodes form a cluster, Kibana connects to ES, Logstash creates its writer user in ES and opens port 5044 for Beats, and Beats ships logs to Logstash. TLS certificates are automatically generated and distributed.

## Disabling security

!!! warning
    Only disable security for isolated development environments. Never run without security on networks accessible to untrusted users.

For internal networks or development environments where TLS is not needed:

```yaml
elasticstack_security: false
```

In full-stack mode (`elasticstack_full_stack: true`), this cascades to all roles — Elasticsearch, Kibana, Logstash, and Beats all inherit the setting. If you are running roles individually (`elasticstack_full_stack: false`), you also need to set the per-role flags:

```yaml
elasticsearch_security: false
beats_security: false
```

## Using a package mirror

If your hosts can't reach `artifacts.elastic.co`, point the repo at a local mirror:

```yaml
elasticstack_repo_base_url: "https://elastic-cache.internal.example.com"
```

Or set the `ELASTICSTACK_REPO_BASE_URL` environment variable.

## Configuring Beats inputs

The Beats role supports several input types. Here's a more complete example:

```yaml
# Filebeat with multiple log inputs
beats_filebeat: true
beats_filebeat_output: logstash
beats_filebeat_log_inputs:
  syslog:
    name: syslog
    paths:
      - /var/log/syslog
      - /var/log/messages
  nginx:
    name: nginx
    paths:
      - /var/log/nginx/access.log
      - /var/log/nginx/error.log
    fields:
      app: nginx

# Syslog TCP/UDP listeners
beats_filebeat_syslog_tcp: true
beats_filebeat_syslog_tcp_port: 5514
beats_filebeat_syslog_tcp_fields:
  source_protocol: tcp

beats_filebeat_syslog_udp: true
beats_filebeat_syslog_udp_port: 5515
beats_filebeat_syslog_udp_fields:
  source_protocol: udp

# Journald input
beats_filebeat_journald: true

# Disk-backed queue for reliability
beats_queue_type: disk
beats_queue_disk_max_size: 2GB

# Metricbeat for system metrics
beats_metricbeat: true
beats_metricbeat_modules:
  - system
```

## Custom Logstash pipelines

For simple cases, use inline filters:

```yaml
logstash_filters: |
  grok {
    match => { "message" => "%{SYSLOGLINE}" }
  }
```

For complex pipelines, use filter files:

```yaml
logstash_filter_files:
  - files/logstash/10-syslog.conf
  - files/logstash/20-nginx.conf
```

Or take full control with a custom pipeline:

```yaml
logstash_custom_pipeline: |
  input {
    beats { port => 5044 }
  }
  filter {
    grok { match => { "message" => "%{SYSLOGLINE}" } }
  }
  output {
    elasticsearch {
      hosts => ["https://es1:9200"]
      index => "logs-%{+YYYY.MM.dd}"
    }
  }
```

## Upgrading from 8.x to 9.x

Set the target version and run the playbook:

```yaml
elasticstack_release: 9
elasticstack_version: "9.0.2"
```

The Elasticsearch role detects the version mismatch and performs a rolling upgrade automatically — one node at a time with shard allocation management. All other roles simply upgrade their packages.

!!! important
    All nodes must be running **8.19.x** before upgrading to 9.x. The role enforces this: if any node is on an older 8.x version, the play fails immediately with an upgrade path violation error. This matches [Elastic's official upgrade requirements](https://www.elastic.co/docs/deploy-manage/upgrade/deployment-or-cluster).

## Certificate renewal

Certificates are checked on every run and renewed automatically when they approach expiry (default: 30 days before). To force renewal, use tags:

```bash
# Renew all certificates
ansible-playbook -i inventory.yml playbook.yml --tags certificates

# Renew only Elasticsearch certificates
ansible-playbook -i inventory.yml playbook.yml --tags renew_es_cert

# Renew only the CA (triggers renewal of all dependent certs)
ansible-playbook -i inventory.yml playbook.yml --tags renew_ca
```

## Next steps

- Review the [Architecture](../guide/architecture.md) page for how roles interact
- Browse the role reference pages for all available variables: [elasticsearch](../reference/elasticsearch.md), [kibana](../reference/kibana.md), [logstash](../reference/logstash.md), [beats](../reference/beats.md), [elasticstack](../reference/elasticstack.md), [repos](../reference/repos.md)
