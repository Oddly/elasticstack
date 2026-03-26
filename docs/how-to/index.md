# Recipes

Common deployment patterns and answers to frequently asked questions.

## Kibana behind a reverse proxy

When Kibana sits behind nginx, Caddy, or a load balancer that terminates TLS, leave Kibana's own TLS off and let the proxy handle HTTPS:

```yaml title="group_vars/kibana.yml"
kibana_tls: false   # default — Kibana serves plain HTTP on :5601

kibana_extra_config:
  server.basePath: "/kibana"           # if proxied under a subpath
  server.rewriteBasePath: true
  server.publicBaseUrl: "https://kibana.example.com/kibana"
```

```nginx title="nginx site config"
upstream kibana {
    server kb1:5601;
}

server {
    listen 443 ssl;
    server_name kibana.example.com;

    ssl_certificate     /etc/letsencrypt/live/kibana.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/kibana.example.com/privkey.pem;

    location /kibana/ {
        proxy_pass http://kibana/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

If you want Kibana itself to serve HTTPS (no proxy), set `kibana_tls: true` and provide certificates. See the [TLS page](../guide/tls.md) for examples.

## Kibana with HTTPS enabled (no proxy)

```yaml title="group_vars/kibana.yml"
kibana_tls: true
# Auto-generated cert from ES CA (default):
kibana_cert_source: elasticsearch_ca

# Or with an external cert:
# kibana_cert_source: external
# kibana_tls_certificate_file: /etc/pki/kibana/kibana.crt
# kibana_tls_key_file: /etc/pki/kibana/kibana.key
# kibana_tls_ca_file: /etc/pki/kibana/ca.crt
```

## Standalone Logstash (no Elasticsearch CA)

When Logstash runs independently and doesn't share the Elasticsearch CA:

```yaml title="group_vars/logstash.yml"
elasticstack_full_stack: false
logstash_cert_source: standalone   # self-signed CA + server cert

# Explicit ES hosts since auto-discovery is off
logstash_elasticsearch_hosts:
  - "https://es1.example.com"
  - "https://es2.example.com"
```

In standalone mode, Logstash still creates its `logstash_writer` user and role in Elasticsearch. The `external` mode skips user/role creation entirely.

## Beats shipping directly to Elasticsearch

Skip Logstash entirely and send Beats output straight to ES:

```yaml title="group_vars/beats.yml"
beats_filebeat_output: elasticsearch
beats_auditbeat_output: elasticsearch
beats_metricbeat_output: elasticsearch
beats_security: true   # enable TLS for the ES connection
```

When `beats_security: true`, Beats verifies the Elasticsearch TLS certificate and authenticates with a client certificate. In full-stack mode, the certificate is fetched from the ES CA automatically.

## Adding a node to an existing Elasticsearch cluster

1. Add the new host to the `elasticsearch` inventory group
2. Run the playbook — the role detects the new node and includes it in `discovery.seed_hosts`
3. The existing cluster auto-accepts the new node because it trusts the same CA

```yaml title="inventory.yml — add es4"
elasticsearch:
  hosts:
    es1: { ansible_host: 10.0.1.10 }
    es2: { ansible_host: 10.0.1.11 }
    es3: { ansible_host: 10.0.1.12 }
    es4: { ansible_host: 10.0.1.13 }   # new node
```

```bash
ansible-playbook -i inventory.yml playbook.yml
```

The CA generates a new certificate for `es4`, distributes it, and the node joins the cluster. Existing nodes are updated with the new `discovery.seed_hosts` list.

!!! note
    If you're adding your first even-numbered master-eligible node (e.g. going from 3 to 4), the role will fail with a quorum warning. Either add the node as data-only (`elasticsearch_node_types: ["data", "ingest"]`) or add two nodes at once to maintain an odd master count.

## Dedicated node roles (hot/warm/cold)

For tiered storage architectures:

```yaml title="host_vars/es-hot1.yml"
elasticsearch_node_types: ["master", "data_hot", "ingest"]
elasticsearch_heap: 16
elasticstack_temperature: hot
```

```yaml title="host_vars/es-warm1.yml"
elasticsearch_node_types: ["data_warm"]
elasticsearch_heap: 8
elasticstack_temperature: warm
```

```yaml title="host_vars/es-cold1.yml"
elasticsearch_node_types: ["data_cold"]
elasticsearch_heap: 4
elasticstack_temperature: cold
```

The `elasticstack_temperature` variable sets `node.attr.temp` in `elasticsearch.yml`, which ILM policies use for data tier routing.

## `elasticsearch_extra_config` vs `elasticsearch_cluster_settings`

Two ways to configure Elasticsearch, for different purposes:

**`elasticsearch_extra_config`** writes settings to `elasticsearch.yml`. These are node-level, static settings that require a restart to change.

```yaml
elasticsearch_extra_config:
  http.cors.enabled: true
  http.cors.allow-origin: "https://my-app.example.com"
  action.destructive_requires_name: true
  thread_pool.search.size: 30
```

**`elasticsearch_cluster_settings`** applies settings via the `PUT _cluster/settings` API. These are cluster-wide, dynamic settings that take effect immediately without a restart.

```yaml
elasticsearch_cluster_settings:
  cluster.routing.allocation.disk.watermark.low: "90%"
  cluster.routing.allocation.disk.watermark.high: "95%"
  indices.recovery.max_bytes_per_sec: "100mb"
  cluster.logsdb.enabled: true
```

Rule of thumb: if the Elasticsearch docs say a setting is "dynamic", use `elasticsearch_cluster_settings`. If it says "static" or "node-level", use `elasticsearch_extra_config`.

## `elasticstack_full_stack: false` — when and why

The `elasticstack_full_stack` flag (default `true`) controls whether roles auto-discover each other through inventory groups. Set it to `false` when:

- You're deploying a single service (just Elasticsearch, or just Beats)
- Your Ansible inventory doesn't contain all stack components
- Services are managed by different teams with separate inventories
- You need explicit control over host lists

```yaml title="group_vars/all.yml"
elasticstack_full_stack: false
```

When disabled, you must provide explicit host lists for cross-service connections:

```yaml
# Beats needs to know where Logstash is
beats_target_hosts:
  - "logstash1.example.com"
  - "logstash2.example.com"

# Logstash needs to know where Elasticsearch is
logstash_elasticsearch_hosts:
  - "https://es1.example.com"
  - "https://es2.example.com"
```

## Simplifying passwords with `elasticstack_cert_pass`

Instead of setting a separate passphrase for each service's TLS key, use the global shortcut:

```yaml title="group_vars/all.yml"
# One passphrase for all TLS keys
elasticstack_cert_pass: "{{ vault_cert_pass }}"

# This replaces setting all of these individually:
# elasticsearch_tls_key_passphrase: "..."
# kibana_tls_key_passphrase: "..."
# logstash_tls_key_passphrase: "..."
# beats_tls_key_passphrase: "..."
```

Per-service passphrases still override `elasticstack_cert_pass` when set, so you can start simple and split later if needed.

## Air-gapped / offline deployment

When hosts cannot reach `artifacts.elastic.co`:

```yaml title="group_vars/all.yml"
elasticstack_repo_base_url: "https://elastic-cache.internal.example.com"
```

Set up a caching reverse proxy (Nginx, Caddy, Nexus, Artifactory) that mirrors `artifacts.elastic.co` and point this variable at it. The GPG key URL auto-derives from the base URL.

You can also set this as an environment variable:

```bash
export ELASTICSTACK_REPO_BASE_URL=https://elastic-cache.internal.example.com
ansible-playbook -i inventory.yml playbook.yml
```

## Filebeat with multiple log inputs

```yaml title="group_vars/beats.yml"
beats_filebeat: true
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
  application:
    name: myapp
    paths:
      - /var/log/myapp/*.log
    fields:
      app: myapp
      env: production
```

## Logstash with complex pipelines

For pipelines that outgrow inline filters, use filter files:

```yaml title="group_vars/logstash.yml"
logstash_filter_files:
  - files/logstash/10-syslog.conf
  - files/logstash/20-nginx.conf
  - files/logstash/30-app.conf
```

Or take full control with `logstash_custom_pipeline`:

```yaml title="group_vars/logstash.yml"
logstash_custom_pipeline: |
  input {
    beats { port => 5044 }
    http { port => 8080 }
  }
  filter {
    if [fields][app] == "nginx" {
      grok { match => { "message" => "%{COMBINEDAPACHELOG}" } }
      geoip { source => "clientip" }
    }
  }
  output {
    if [fields][app] == "nginx" {
      elasticsearch {
        hosts => ["https://es1:9200"]
        index => "nginx-%{+YYYY.MM.dd}"
      }
    } else {
      elasticsearch {
        hosts => ["https://es1:9200"]
        index => "logs-%{+YYYY.MM.dd}"
      }
    }
  }
```

## Suppressing sensitive output for debugging

When troubleshooting authentication or certificate issues, temporarily disable log suppression:

```yaml
elasticstack_no_log: false   # show passwords and cert contents in Ansible output
```

Remember to re-enable it (`true`, the default) after debugging.

## Snapshot repository setup

Configure filesystem paths for Elasticsearch snapshots:

```yaml title="group_vars/elasticsearch.yml"
elasticsearch_fs_repo:
  - /mnt/backups/elasticsearch
  - /mnt/nfs/snapshots

elasticsearch_extra_config:
  # Optional: set up the repository via the API
  # (or do it manually via Kibana after deployment)
```

The paths must be accessible from every ES node (typically shared NFS mounts). The role sets `path.repo` in `elasticsearch.yml`.
