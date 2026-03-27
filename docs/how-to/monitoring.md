# Monitoring & Observability

## Self-monitoring with Beats

Use Metricbeat and Filebeat to monitor the Elastic Stack itself.

### Metricbeat for cluster metrics

```yaml title="group_vars/beats.yml"
beats_metricbeat: true
beats_metricbeat_modules:
  - system
  - elasticsearch-xpack  # ships ES cluster metrics
  - kibana-xpack         # ships Kibana metrics
  - logstash-xpack       # ships Logstash metrics
```

The `-xpack` module variants ship data in the format that Kibana's Stack Monitoring expects. After deployment, open **Stack Monitoring** in Kibana to see cluster health, node stats, and index metrics.

### Filebeat for log collection

```yaml title="group_vars/beats.yml"
beats_filebeat: true
beats_filebeat_modules:
  - system        # syslog, auth logs
  - elasticsearch # ES JSON logs
  - kibana        # Kibana JSON logs
  - logstash      # Logstash JSON logs
```

### Audit logs

Ship Elasticsearch audit logs to a dedicated index:

```yaml title="group_vars/elasticsearch.yml"
elasticsearch_extra_config:
  xpack.security.audit.enabled: true
```

Then configure Filebeat to pick up the audit log file:

```yaml
beats_filebeat_log_inputs:
  es_audit:
    name: es-audit
    paths:
      - /var/log/elasticsearch/*_audit.json
    fields:
      type: audit
```

## Health check endpoints

After deployment, verify health from the command line:

```bash
# Elasticsearch cluster health
curl -sk -u elastic:PASSWORD https://localhost:9200/_cluster/health?pretty

# Kibana status (use https if kibana_tls: true)
curl -sk -u elastic:PASSWORD https://localhost:5601/api/status

# Logstash pipeline stats (no auth required, localhost only)
curl -s http://localhost:9600/_node/stats/pipelines?pretty
```
