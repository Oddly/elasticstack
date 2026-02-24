# Kibana Role

Deploys and manages Kibana — service management, TLS encryption for the web UI, and Elasticsearch connection setup.

## Custom TLS Certificates

Set `kibana_cert_source: external` to use your own certificates instead of the auto-generated ones.

```yaml
kibana_cert_source: external
kibana_tls_certificate_file: /path/to/kibana.crt
kibana_tls: true  # enable HTTPS on Kibana's web interface
```

The format (PEM vs P12) is auto-detected. For PEM, the key is derived from the cert path by default. Set `kibana_tls_remote_src: true` if files are already on the managed node.

### Inline PEM content

Pass certificate content directly as variables instead of file paths:

```yaml
kibana_cert_source: external
kibana_tls_certificate_content: "{{ lookup('hashi_vault', 'secret/kibana/cert') }}"
kibana_tls_key_content: "{{ lookup('hashi_vault', 'secret/kibana/key') }}"
kibana_tls_ca_content: "{{ lookup('hashi_vault', 'secret/kibana/ca') }}"
```

Content variables take precedence over file paths. Content mode is always PEM.

### Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `kibana_cert_source` | `elasticsearch_ca` | `elasticsearch_ca` or `external` |
| `kibana_tls_certificate_file` | `""` | Certificate path (PEM or P12) |
| `kibana_tls_key_file` | `""` | Key file (auto-derived for PEM) |
| `kibana_tls_certificate_passphrase` | `""` | Passphrase for encrypted key/P12 |
| `kibana_tls_ca_file` | `""` | CA cert (auto-extracted from PEM chain) |
| `kibana_tls_remote_src` | `false` | `true` if cert files are on the managed node |
| `kibana_tls_certificate_content` | `""` | Certificate as inline PEM string |
| `kibana_tls_key_content` | `""` | Key as inline PEM string |
| `kibana_tls_ca_content` | `""` | CA cert as inline PEM string |
