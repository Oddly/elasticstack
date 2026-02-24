# Beats Role

Deploys and manages Elastic Beats — Filebeat, Metricbeat, and Auditbeat with syslog, journald, and Docker inputs.

## Custom TLS Certificates

Set `beats_cert_source: external` to use your own certificates instead of the auto-generated ones. Beats uses PEM format natively.

```yaml
beats_cert_source: external
beats_tls_certificate_file: /path/to/beats.crt
```

The key is derived from the cert path by default (`.crt` → `.key`). Set `beats_tls_remote_src: true` if files are already on the managed node.

### Inline PEM content

Pass certificate content directly as variables instead of file paths:

```yaml
beats_cert_source: external
beats_tls_certificate_content: "{{ lookup('hashi_vault', 'secret/beats/cert') }}"
beats_tls_key_content: "{{ lookup('hashi_vault', 'secret/beats/key') }}"
beats_tls_ca_content: "{{ lookup('hashi_vault', 'secret/beats/ca') }}"
```

Content variables take precedence over file paths. Content mode is always PEM.

### Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `beats_cert_source` | `elasticsearch_ca` | `elasticsearch_ca` or `external` |
| `beats_tls_certificate_file` | `""` | Certificate path (PEM) |
| `beats_tls_key_file` | `""` | Key file (auto-derived for PEM) |
| `beats_tls_ca_file` | `""` | CA cert (auto-extracted from PEM chain) |
| `beats_tls_remote_src` | `false` | `true` if cert files are on the managed node |
| `beats_tls_certificate_content` | `""` | Certificate as inline PEM string |
| `beats_tls_key_content` | `""` | Key as inline PEM string |
| `beats_tls_ca_content` | `""` | CA cert as inline PEM string |
