# Security

## How security bootstrapping works

On a fresh deployment, the Elasticsearch role handles the full security setup automatically:

1. **Bootstrap password** — sets a temporary password in the keystore for initial cluster formation
2. **Cluster start** — Elasticsearch starts with security enabled
3. **Password generation** — creates random passwords for built-in users (`elastic`, `kibana_system`, `logstash_system`, etc.) and writes them to `/usr/share/elasticsearch/initial_passwords`
4. **User and role creation** — creates the `logstash_writer` role and user for Logstash output
5. **Password distribution** — other roles (Kibana, Logstash, Beats) read the generated passwords from the CA host

On subsequent runs, the role detects the existing security setup and skips initialization.

## Built-in users

| User | Purpose | Where it's used |
|------|---------|-----------------|
| `elastic` | Superuser | Admin access, initial setup |
| `kibana_system` | Kibana backend | Kibana → Elasticsearch connection |
| `logstash_system` | Logstash monitoring | Logstash → Elasticsearch monitoring |
| `logstash_writer` | Logstash output | Logstash → Elasticsearch data ingestion |

## Custom passwords

### Setting the `kibana_system` password

By default, `kibana_system` uses the auto-generated password from initial setup. To set a specific password:

```yaml
kibana_system_password: "my-known-password"
```

The Kibana role changes the password via the Elasticsearch security API and configures Kibana to use it. Useful for external monitoring or multi-Kibana deployments that need a consistent password.

### Custom keystore entries

Store sensitive settings in the Elasticsearch keystore instead of `elasticsearch.yml`:

```yaml
elasticsearch_keystore_entries:
  xpack.notification.slack.account.monitoring.secure_url: "https://hooks.slack.com/services/T00/B00/XXX"
  xpack.notification.email.account.work.smtp.secure_password: "smtp-password"
  s3.client.default.access_key: "AKIAIOSFODNN7EXAMPLE"
  s3.client.default.secret_key: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
```

Values are passed via stdin — they never appear in process listings or Ansible logs. The role only writes entries that have changed, so Elasticsearch is only restarted when a value actually differs.

Entries removed from the dictionary are automatically cleaned up from the keystore on the next run.

!!! warning
    Don't set role-managed keys (bootstrap password, SSL keystore passwords) via `elasticsearch_keystore_entries` — the role manages those automatically. It will fail with a clear error if you try.

## Audit logging

Audit logging tracks who did what and when — authentication attempts, authorization decisions, and security-sensitive operations.

### Enabling audit logs

```yaml
elasticsearch_extra_config:
  xpack.security.audit.enabled: true
```

Audit logs are written to `/var/log/elasticsearch/<cluster>_audit.json` as structured JSON, one event per line.

### Choosing which events to log

By default, Elasticsearch logs all event types. For most environments, a targeted set reduces noise while catching what matters:

```yaml
elasticsearch_extra_config:
  xpack.security.audit.enabled: true
  xpack.security.audit.logfile.events.include:
    - authentication_success       # successful sign-ins
    - authentication_failed        # failed sign-in attempts
    - access_denied                # authorization failures
    - access_granted               # successful authorization (verbose)
    - connection_denied            # IP filter rejections
    - tampered_request             # requests with invalid auth tokens
    - run_as_denied                # run-as impersonation denied
    - run_as_granted               # run-as impersonation allowed
  xpack.security.audit.logfile.events.exclude:
    - anonymous_access_denied      # health check noise
```

For a minimal setup that catches security incidents without high volume, use only `authentication_failed`, `access_denied`, and `tampered_request`.

### Filtering by user or index

Reduce volume further by focusing on sensitive indices or excluding service accounts:

```yaml
elasticsearch_extra_config:
  xpack.security.audit.enabled: true
  xpack.security.audit.logfile.events.ignore_filters:
    system_filter:
      users: ["_xpack_security", "kibana_system", "logstash_system"]
    internal_indices:
      indices: [".kibana*", ".security*", ".async-search*"]
```

This excludes the high-volume internal traffic from service accounts and system indices.

### Shipping audit logs

Audit logs should be shipped to a **separate cluster or SIEM** — never only to the cluster being audited. Use Filebeat:

```yaml title="group_vars/beats.yml"
beats_filebeat: true
beats_filebeat_log_inputs:
  es_audit:
    name: es-audit
    paths:
      - /var/log/elasticsearch/*_audit.json
    fields:
      type: audit
```

### What audit events look like

Each event is a JSON object:

```json
{
  "type": "audit",
  "timestamp": "2026-03-27T10:15:23,456+0000",
  "event.type": "authentication_failed",
  "user.name": "admin",
  "origin.address": "192.168.1.50",
  "realm": "native",
  "request.name": "ClusterHealthAction"
}
```

Key fields: `event.type` (what happened), `user.name` (who), `origin.address` (from where), `request.name` (what API action).

## Disabling security

For development environments where TLS and authentication are not needed:

```yaml
elasticsearch_http_security: false
elasticsearch_security: false
```

!!! warning
    Never disable security in production. An unsecured Elasticsearch cluster is accessible to anyone who can reach port 9200.
