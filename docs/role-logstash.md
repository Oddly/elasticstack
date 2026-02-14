# Ansible Role: Logstash

![Test Role Logstash](https://github.com/Oddly/ansible-collection-elasticstack/actions/workflows/test_role_logstash.yml/badge.svg)

This role installs and configures [Logstash](https://www.elastic.co/products/logstash) on Linux systems.

## Quick Start

Zero-config deployment with sensible defaults:

```yaml
- hosts: logstash
  roles:
    - oddly.elasticstack.repos
    - oddly.elasticstack.logstash
```

This gives you:
- Beats input on port 5044
- Elasticsearch output (auto-discovered from inventory)
- TLS enabled in full stack mode

## Pipeline Configuration

### Default Pipeline (Recommended)

The simplest approach - just add your filters:

```yaml
logstash_filters: |
  grok {
    match => { "message" => "%{SYSLOGLINE}" }
  }
  date {
    match => [ "timestamp", "MMM  d HH:mm:ss", "MMM dd HH:mm:ss" ]
  }
```

### Filter Files

Copy filter files from your playbook:

```yaml
logstash_filter_files:
  - files/logstash/syslog-filter.conf
  - files/logstash/nginx-filter.conf
```

### Extra Inputs/Outputs

Add additional inputs or outputs alongside defaults:

```yaml
logstash_extra_inputs: |
  http {
    port => 8080
  }

logstash_extra_outputs: |
  file {
    path => "/var/log/logstash/debug.log"
  }
```

### Custom Pipeline (Full Control)

For complete control, use a custom pipeline:

```yaml
logstash_custom_pipeline: |
  input {
    generator {
      message => "test"
      count => 1
    }
  }
  filter {
    mutate {
      add_field => { "custom" => "value" }
    }
  }
  output {
    stdout { codec => rubydebug }
  }
```

## Input Configuration

### Beats Input

```yaml
logstash_input_beats: true           # Enable beats input (default)
logstash_input_beats_port: 5044      # Listen port
logstash_input_beats_ssl: true       # Enable TLS
```

### Elastic Agent Input

```yaml
logstash_input_elastic_agent: true   # Enable elastic_agent input
logstash_input_elastic_agent_port: 5044
logstash_input_elastic_agent_ssl: true  # Required for production
```

## Output Configuration

### Elasticsearch Output

```yaml
logstash_output_elasticsearch: true  # Enable ES output (default)
logstash_elasticsearch_hosts:        # Manual hosts (or auto-discover)
  - "es1.example.com:9200"
  - "es2.example.com:9200"
logstash_elasticsearch_index: "logs-%{+YYYY.MM.dd}"  # Custom index pattern
```

## Certificate Management

### Using Elasticsearch CA (Default)

When used with the full Elastic Stack, certificates are automatically generated:

```yaml
elasticstack_full_stack: true
# Certificates auto-generated from ES CA
```

### External Certificates

Bring your own certificates:

```yaml
logstash_cert_source: external
logstash_tls_certificate_file: "/path/to/server.crt"
logstash_tls_key_file: "/path/to/server.key"
logstash_tls_ca_file: "/path/to/ca.crt"
```

### Certificate Renewal

Automatic renewal when certificates approach expiration:

```yaml
logstash_cert_validity_period: 365   # Days certs are valid
logstash_cert_expiration_buffer: 30  # Renew when this many days left
```

Force regeneration:

```yaml
logstash_cert_force_regenerate: true
```

Or via tag:

```bash
ansible-playbook site.yml --tags renew_logstash_cert
```

## Standalone Mode

Run Logstash without Elasticsearch integration:

```yaml
logstash_output_elasticsearch: false
logstash_create_user: false
logstash_create_role: false
logstash_input_beats_ssl: false

logstash_extra_outputs: |
  file {
    path => "/var/log/logstash/output.log"
  }
```

## Requirements

- `community.general` collection
- `community.crypto` collection (for external certificate mode)
- Elastic Repos configured (use `oddly.elasticstack.repos` role)
- `passlib` Python library for password hashing

## All Variables Reference

### Service Management

| Variable | Default | Description |
|----------|---------|-------------|
| `logstash_enable` | `true` | Start and enable Logstash service |
| `logstash_config_backup` | `false` | Keep backups of config changes |
| `logstash_manage_yaml` | `true` | Manage logstash.yml |
| `logstash_manage_logging` | `false` | Manage log4j configuration |
| `logstash_plugins` | `[]` | List of plugins to install |

### Pipeline Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `logstash_manage_pipelines` | `true` | Manage pipelines.yml |
| `logstash_no_pipelines` | `false` | Disable all pipeline management |
| `logstash_queue_type` | `persisted` | Queue type (persisted/memory) |
| `logstash_queue_max_bytes` | `1gb` | Maximum queue size |
| `logstash_filters` | `""` | Inline filter configuration |
| `logstash_filter_files` | `[]` | Filter files to copy |
| `logstash_extra_inputs` | `""` | Additional input configuration |
| `logstash_extra_outputs` | `""` | Additional output configuration |
| `logstash_custom_pipeline` | `""` | Complete custom pipeline |

### Input Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `logstash_input_beats` | `true` | Enable beats input |
| `logstash_input_beats_port` | `5044` | Beats listen port |
| `logstash_input_beats_ssl` | auto | Enable TLS for beats |
| `logstash_input_elastic_agent` | `false` | Enable elastic_agent input |
| `logstash_input_elastic_agent_port` | `5044` | Agent listen port |
| `logstash_input_elastic_agent_ssl` | `true` | Enable TLS for agent |

### Output Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `logstash_output_elasticsearch` | `true` | Enable ES output |
| `logstash_elasticsearch_hosts` | `[]` | ES hosts (empty = auto-discover) |
| `logstash_elasticsearch_index` | `""` | Custom index pattern |
| `logstash_elasticsearch_ssl` | `true` | Use HTTPS for ES |
| `logstash_validate_after_inactivity` | `300` | Connection validation interval |
| `logstash_sniffing` | `false` | Enable ES sniffing |

### Certificate Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `logstash_cert_source` | `elasticsearch_ca` | Certificate source mode |
| `logstash_certs_dir` | `/etc/logstash/certs` | Certificate directory |
| `logstash_cert_validity_period` | `1095` | Cert validity (days) |
| `logstash_cert_expiration_buffer` | `30` | Renewal threshold (days) |
| `logstash_cert_force_regenerate` | `false` | Force cert regeneration |
| `logstash_tls_key_passphrase` | `LogstashChangeMe` | Key passphrase |
| `logstash_tls_certificate_file` | - | External cert path |
| `logstash_tls_key_file` | - | External key path |
| `logstash_tls_ca_file` | - | External CA path |

### User/Role Management

| Variable | Default | Description |
|----------|---------|-------------|
| `logstash_create_role` | `true` | Create ES role |
| `logstash_role_name` | `logstash_writer` | Role name |
| `logstash_create_user` | `true` | Create ES user |
| `logstash_user_name` | `logstash_writer` | User name |
| `logstash_user_password` | `password` | User password |

### Event Enrichment

| Variable | Default | Description |
|----------|---------|-------------|
| `logstash_ident` | `true` | Add instance identifier |
| `logstash_ident_field_name` | `[logstash][instance]` | Identifier field name |
| `logstash_pipeline_identifier` | `true` | Add pipeline identifier |

### Full Stack Integration

| Variable | Default | Description |
|----------|---------|-------------|
| `elasticstack_full_stack` | `false` | Full stack mode |
| `elasticstack_release` | `8` | Major release version |
| `elasticstack_version` | - | Specific version to install |
| `elasticstack_ca_dir` | `/opt/es-ca` | CA directory |
| `elasticstack_ca_pass` | `PleaseChangeMe` | CA password |

## Usage Examples

### Basic with Filters

```yaml
- name: Install Logstash with syslog parsing
  hosts: logstash
  collections:
    - oddly.elasticstack
  vars:
    logstash_filters: |
      grok {
        match => { "message" => "%{SYSLOGLINE}" }
      }
  roles:
    - repos
    - logstash
```

### Full Stack with Elasticsearch

```yaml
- name: Full Elastic Stack
  hosts: all
  collections:
    - oddly.elasticstack
  vars:
    elasticstack_full_stack: true
    elasticstack_release: 9
  roles:
    - repos

- hosts: elasticsearch
  roles:
    - elasticsearch

- hosts: logstash
  roles:
    - logstash

- hosts: kibana
  roles:
    - kibana
```

### Standalone with File Output

```yaml
- name: Standalone Logstash
  hosts: logstash
  collections:
    - oddly.elasticstack
  vars:
    logstash_output_elasticsearch: false
    logstash_input_beats_ssl: false
    logstash_extra_outputs: |
      file {
        path => "/var/log/logstash/events-%{+YYYY-MM-dd}.log"
      }
  roles:
    - repos
    - logstash
```
