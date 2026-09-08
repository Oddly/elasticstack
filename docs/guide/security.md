# Security

## How security bootstrapping works

On a fresh deployment, the Elasticsearch role handles the full security setup automatically:

1. **Bootstrap password** — sets a temporary password in the keystore for initial cluster formation
2. **Cluster start** — Elasticsearch starts with security enabled
3. **Password generation** — creates random passwords for built-in users (`elastic`, `kibana_system`, `logstash_system`, etc.) and writes them to `/usr/share/elasticsearch/initial_passwords`
4. **User and role creation** — creates the `logstash_writer` role and user for Logstash output when `logstash_create_user` is enabled; this requires an explicit `logstash_user_password`
5. **Password distribution** — other roles (Kibana, Logstash, Beats) read the generated passwords from the CA host

On subsequent runs, the role detects the existing security setup and skips initialization.

## Built-in users

| User | Purpose | Where it's used |
|------|---------|-----------------|
| `elastic` | Superuser | Admin access, initial setup |
| `kibana_system` | Kibana backend | Kibana → Elasticsearch connection |
| `logstash_system` | Logstash monitoring | Logstash → Elasticsearch monitoring |
| `beats_system` | Beats monitoring | Beats → Elasticsearch monitoring |
| `apm_system` | APM server | APM server → Elasticsearch |
| `remote_monitoring_user` | Stack monitoring | Monitoring collection |

`logstash_writer` is a collection-created custom user, not an Elasticsearch
built-in user. Its password has no safe default and must be supplied through
`logstash_user_password` when Logstash creates it.

## Default and generated credentials

These placeholder values are published defaults for development and test
deployments. They are known strings, not secrets, and must be replaced before
the collection manages a production environment:

| Variable | Default | Protects |
|----------|---------|----------|
| `elasticstack_ca_pass` | `PleaseChangeMe` | Generated CA private key |
| `elasticsearch_bootstrap_pw` | `PleaseChangeMe` | Temporary Elasticsearch bootstrap state |
| `elasticsearch_tls_key_passphrase` | `PleaseChangeMeIndividually` | Elasticsearch node private keys |
| `kibana_tls_key_passphrase` | `PleaseChangeMe` | Kibana TLS private key |
| `logstash_tls_key_passphrase` | `LogstashChangeMe` | Logstash TLS keystore |
| `beats_tls_key_passphrase` | `BeatsChangeMe` | Beats private key |

`elasticsearch_elastic_password`, `kibana_system_password`, and
`logstash_user_password` are empty by default. An empty value does not create
an empty login: the first two use generated or explicitly rotated credentials,
while `logstash_user_password` must be supplied when the collection creates
`logstash_writer` or configures a secured standard output.

For production, put the CA and bootstrap values in Ansible Vault or a secrets
manager, set `elasticstack_cert_pass` to a vaulted shared TLS passphrase (or
set each service passphrase separately), and provide explicit service account
passwords when a stable login is required. Keep `elasticstack_no_log: true` and
protect the `elasticstack_initial_passwords` file; it contains generated
credentials for built-in users until you rotate them deliberately.

## Custom passwords

### Setting the `kibana_system` password

By default, `kibana_system` uses the auto-generated password from initial setup. To set a specific password:

```yaml
kibana_system_password: "my-known-password"
```

The Kibana role changes the password via the Elasticsearch security API and configures Kibana to use it. Useful for external monitoring or multi-Kibana deployments that need a consistent password.

## Declarative users, roles, and role mappings

The Elasticsearch role can manage native security objects after the cluster is
initialized. The API calls run once through the CA host using the `elastic`
credential that the role fetched from `elasticstack_initial_passwords`, or the
value supplied through `elasticsearch_elastic_password`.

Define custom roles before users and LDAP or Active Directory mappings:

```yaml
elasticsearch_security_roles:
  - name: app_writer
    cluster: [monitor]
    indices:
      - names: ["app-*"]
        privileges: [read, write]

elasticsearch_users:
  - name: app_ingest
    password: "{{ vault_app_ingest_password }}"
    roles: [app_writer]
    full_name: Application ingest user

elasticsearch_role_mappings:
  - name: app_admins
    roles: [app_writer]
    rules:
      field:
        groups: "cn=app-admins,dc=example,dc=com"
```

The account used by the role needs the `manage_security` privilege. Role
mappings reference roles and do not create them, so declare a referenced role
in `elasticsearch_security_roles` first.

New custom users require `password` or `password_hash`. Passwords are sent
only to the security API under `no_log`; keep them in Ansible Vault or a
secrets manager. The API does not return a user's password, so an existing
user's password is left alone on repeated runs. Set `password_update: true`
for an intentional rotation:

```yaml
elasticsearch_users:
  - name: app_ingest
    password: "{{ vault_new_app_ingest_password }}"
    password_update: true
    roles: [app_writer]
```

Built-in passwords are explicit rotations because Elasticsearch cannot expose
the current secret for comparison:

```yaml
elasticsearch_builtin_passwords:
  kibana_system: "{{ vault_kibana_system_password }}"
  logstash_system: "{{ vault_logstash_system_password }}"
  beats_system: "{{ vault_beats_system_password }}"
  remote_monitoring_user: "{{ vault_remote_monitoring_password }}"
```

The map is applied on every run that contains an entry. Use
`elasticsearch_elastic_password` for the `elastic` superuser so the role can
continue authenticating after the password changes. The generated
`initial_passwords` file remains the source for built-in passwords until you
replace them deliberately.

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

### Logstash output credentials

`logstash_user_password` has no built-in password. Set it explicitly from Ansible Vault or a secret manager whenever Logstash creates its Elasticsearch user or the secured standard output is enabled. A missing, blank, or too-short value fails before the role changes the host. The generated Logstash pipeline and Kibana configuration are readable by their service group only (`0640`); Kibana's backend password is stored in its keystore rather than rendered into `kibana.yml`.

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
