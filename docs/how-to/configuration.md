# Configuration Recipes

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

## Suppressing sensitive output for debugging

When troubleshooting authentication or certificate issues, temporarily disable log suppression:

```yaml
elasticstack_no_log: false   # show passwords and cert contents in Ansible output
```

Remember to re-enable it (`true`, the default) after debugging.
