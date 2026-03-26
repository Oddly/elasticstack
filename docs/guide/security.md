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

Enable audit logging to track authentication and authorization events:

```yaml
elasticsearch_extra_config:
  xpack.security.audit.enabled: true
```

Audit logs are written to `/var/log/elasticsearch/<cluster>_audit.json` by default. For production, consider shipping them via Filebeat to a separate index.

## Disabling security

For development environments where TLS and authentication are not needed:

```yaml
elasticsearch_http_security: false
elasticsearch_security: false
```

!!! warning
    Never disable security in production. An unsecured Elasticsearch cluster is accessible to anyone who can reach port 9200.
