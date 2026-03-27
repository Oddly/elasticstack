# Best Practices

Opinionated recommendations for running the Elastic Stack in production. These are not hard requirements — adjust to your environment.

## Elasticsearch

### Cluster sizing

- **Minimum 3 master-eligible nodes** for quorum. A 2-node cluster has no fault tolerance — if one node goes down, the other can't form a quorum and the cluster locks up.
- **Odd number of master-eligible nodes** (3, 5, 7) to avoid split-brain during network partitions.
- **Separate roles at scale**: below ~10 nodes, let every node be master + data. Above that, dedicate 3 nodes to master-only and the rest to data.

```yaml title="host_vars/es-master1.yml (large clusters only)"
elasticsearch_node_types: ["master"]
elasticsearch_heap: "4"
```

### JVM heap

- Set heap to **half of available RAM**, up to **30GB max**. The other half is used by the OS for filesystem caching, which Elasticsearch relies on heavily.
- Let the role auto-calculate when possible — it reads cgroup limits in containers and gets this right.
- Never give Elasticsearch all available memory. A 64GB host should have `elasticsearch_heap: "30"`, not `"32"`.

### Memory locking

Always enable in production:

```yaml
elasticsearch_memory_lock: true
```

Swapping destroys Elasticsearch performance. A node that swaps looks like a slow node to the cluster, causes GC storms, and can trigger unnecessary shard relocations.

### Disk watermarks

Tune watermarks before you run out of space, not after:

```yaml
elasticsearch_cluster_settings:
  cluster.routing.allocation.disk.watermark.low: "85%"
  cluster.routing.allocation.disk.watermark.high: "90%"
  cluster.routing.allocation.disk.watermark.flood_stage: "95%"
```

At flood stage, Elasticsearch makes indices read-only. Recovery requires manual intervention (`PUT _all/_settings {"index.blocks.read_only_allow_delete": null}`). Keep enough headroom to avoid hitting it.

### Index Lifecycle Management (ILM)

Don't keep indices open forever. Use ILM policies to:

1. **Rollover** indices when they hit a size or age threshold
2. **Force merge** old indices to reduce segment count
3. **Move** to cheaper storage tiers (warm → cold → frozen)
4. **Delete** when retention expires

This isn't managed by Ansible (it's runtime Elasticsearch config), but make sure your deployment includes ILM policies from day one.

### Slow query logging

Enable slow query logs to catch problematic queries before they cause outages:

```yaml
elasticsearch_cluster_settings:
  index.search.slowlog.threshold.query.warn: "10s"
  index.search.slowlog.threshold.query.info: "5s"
  index.search.slowlog.threshold.fetch.warn: "1s"
  index.indexing.slowlog.threshold.index.warn: "10s"
```

Ship these logs to a monitoring cluster (not the same cluster) via Filebeat.

## Security

### Log all authentication events

Enable audit logging to track sign-ins, failures, and privilege escalations:

```yaml
elasticsearch_extra_config:
  xpack.security.audit.enabled: true
  xpack.security.audit.logfile.events.include:
    - authentication_success
    - authentication_failed
    - access_denied
    - access_granted
    - connection_denied
    - tampered_request
    - run_as_denied
    - run_as_granted
  xpack.security.audit.logfile.events.exclude:
    - anonymous_access_denied   # reduce noise from health checks
```

This writes structured JSON logs to `<cluster>_audit.json`. At minimum, always include `authentication_failed` and `access_denied` — these surface brute-force attempts and misconfigured services.

### Ship audit logs to a separate cluster

Never store audit logs on the cluster being audited — a compromised cluster could delete its own audit trail:

```yaml title="group_vars/beats.yml"
beats_filebeat: true
beats_filebeat_log_inputs:
  es_audit:
    name: es-audit
    paths:
      - /var/log/elasticsearch/*_audit.json
    fields:
      type: audit
      source_cluster: "{{ elasticsearch_cluster_name }}"
```

Point this Filebeat at a separate monitoring/SIEM cluster.

### Rotate the `elastic` superuser password

The `elastic` user has full cluster access. After initial setup:

1. Create named admin accounts with appropriate roles
2. Use API keys for applications instead of username/password
3. Rotate the `elastic` password and store it in a vault

```bash
# Change the elastic password
curl -k -u elastic:OLD_PASSWORD -X POST \
  https://localhost:9200/_security/user/elastic/_password \
  -H 'Content-Type: application/json' \
  -d '{"password": "NEW_PASSWORD"}'
```

### Restrict network exposure

Elasticsearch should never be directly accessible from the internet:

```yaml
elasticsearch_extra_config:
  network.host: ["_site_", "_local_"]   # bind to private + loopback only
  http.host: "0.0.0.0"                  # if Kibana needs to reach it from another host
```

Use firewall rules to restrict port 9200 (HTTP) and 9300 (transport) to known hosts only.

## Kibana

### Use a reverse proxy

Always put Kibana behind a reverse proxy (Nginx, Caddy, HAProxy) in production:

- Terminates TLS with proper certificates (Let's Encrypt, corporate CA)
- Adds security headers (HSTS, CSP, X-Frame-Options)
- Provides rate limiting and access control
- Handles HTTP/2 and compression

See [Kibana behind a reverse proxy](../how-to/deployment.md#kibana-behind-a-reverse-proxy) for a complete nginx example.

### Session and encryption keys

For multi-instance Kibana deployments, set consistent encryption keys so sessions work across instances:

```yaml
kibana_extra_config:
  xpack.security.encryptionKey: "{{ vault_kibana_encryption_key }}"       # min 32 chars
  xpack.encryptedSavedObjects.encryptionKey: "{{ vault_kibana_saved_objects_key }}"
  xpack.reporting.encryptionKey: "{{ vault_kibana_reporting_key }}"
```

Without these, each Kibana instance generates random keys on startup and sessions break when a load balancer sends requests to a different instance.

### Kibana logging

Configure Kibana to log authentication events:

```yaml
kibana_extra_config:
  logging.appenders.security:
    type: rolling-file
    fileName: /var/log/kibana/security.log
    policy:
      type: time-interval
      interval: 24h
    strategy:
      type: numeric
      max: 30
    layout:
      type: json
  logging.loggers:
    - name: plugins.security
      level: info
      appenders: [security]
```

## Logstash

### Persistent queues for durability

If losing events during a Logstash restart is unacceptable:

```yaml
logstash_queue_type: persisted
logstash_queue_max_bytes: "4gb"
```

Use fast storage (SSD/NVMe) for the queue path. Monitor queue depth — if it grows consistently, your output (Elasticsearch) can't keep up.

### Dead letter queue for failed events

Instead of dropping events that fail to index, send them to the DLQ for later analysis:

```yaml
logstash_dead_letter_queue_enable: true
logstash_dead_letter_queue_retain_age: "7d"
```

Check the DLQ periodically for mapping conflicts or malformed events that need pipeline fixes.

## Monitoring

### Monitor the stack itself

At minimum, deploy Metricbeat on all nodes to collect cluster metrics:

```yaml title="group_vars/all.yml"
beats_metricbeat: true
beats_metricbeat_modules:
  - system
  - elasticsearch-xpack
  - kibana-xpack
  - logstash-xpack
```

This feeds Kibana's **Stack Monitoring** dashboards. For production, send these metrics to a separate monitoring cluster so you can still see what's happening when the production cluster is down.

### Alerting

Set up Kibana alerting rules for:

- **Cluster health** goes yellow or red
- **Disk usage** exceeds 80% on any node
- **JVM heap** consistently above 85%
- **Search latency** p95 exceeds your SLA
- **Authentication failures** spike (brute force detection)
- **Audit log volume** drops to zero (logging may be broken)

## Backups

### Snapshot every day

Configure automated snapshots from day one, not after you need them:

```yaml
elasticsearch_fs_repo:
  - /mnt/nfs/es-snapshots
```

After deployment, create an SLM (Snapshot Lifecycle Management) policy via the API or Kibana. Minimum recommended: daily snapshots, 30-day retention.

### Test your restores

A backup that hasn't been tested is not a backup. Schedule quarterly restore tests to a separate cluster to verify:

1. Snapshots are complete and not corrupted
2. Restore procedures are documented and work
3. Restore time fits within your RTO (Recovery Time Objective)
