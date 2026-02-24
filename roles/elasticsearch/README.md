# Elasticsearch Role

Deploys and manages Elasticsearch nodes — cluster formation, JVM tuning, TLS certificate management, security initialization, and rolling upgrades from 8.x to 9.x.

## Custom TLS Certificates

By default the role generates certificates from a built-in CA (`elasticsearch_cert_source: elasticsearch_ca`). To use your own certificates — from a corporate CA, ACME, Vault PKI, etc. — set `elasticsearch_cert_source: external`.

### Minimal configuration

```yaml
# PEM — just set the transport cert; key auto-derived, HTTP reuses transport
elasticsearch_cert_source: external
elasticsearch_transport_tls_certificate: /path/to/server.crt

# P12 — key is bundled in the file
elasticsearch_cert_source: external
elasticsearch_transport_tls_certificate: /path/to/server.p12
```

The format (PEM vs PKCS12) is auto-detected. For PEM, the private key is looked up by replacing the cert extension with `.key` (e.g., `server.crt` → `server.key`). HTTP layer falls back to the transport certificate if `elasticsearch_http_tls_certificate` is empty.

### Separate transport and HTTP certificates

```yaml
elasticsearch_cert_source: external
elasticsearch_transport_tls_certificate: /path/to/transport.crt
elasticsearch_transport_tls_key: /path/to/transport.key
elasticsearch_http_tls_certificate: /path/to/http.crt
elasticsearch_http_tls_key: /path/to/http.key
elasticsearch_tls_ca_certificate: /path/to/ca.crt
```

### Per-host certificates

Use Ansible's `host_vars/` for per-node certs:

```yaml
# host_vars/es-node1.yml
elasticsearch_transport_tls_certificate: /path/to/certs/es-node1.crt
```

Or a wildcard cert in `group_vars/elasticsearch.yml` for all nodes at once.

### Inline PEM content (alternative to file paths)

Instead of pointing to certificate files, you can pass the PEM content directly as Ansible variables. This is useful when certificates come from Vault, AWS Secrets Manager, or any system that provides cert content rather than files. Content variables take precedence over file paths when both are set.

```yaml
elasticsearch_cert_source: external
elasticsearch_transport_tls_certificate_content: "{{ lookup('hashi_vault', 'secret/es/transport-cert') }}"
elasticsearch_transport_tls_key_content: "{{ lookup('hashi_vault', 'secret/es/transport-key') }}"
elasticsearch_tls_ca_certificate_content: "{{ lookup('hashi_vault', 'secret/es/ca-cert') }}"
```

Content mode is always PEM (PKCS12 is binary and not suitable for YAML variables). HTTP content variables fall back to transport content, same as file paths.

### Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `elasticsearch_cert_source` | `elasticsearch_ca` | `elasticsearch_ca` or `external` |
| `elasticsearch_transport_tls_certificate` | `""` | Transport cert path (PEM or P12) |
| `elasticsearch_transport_tls_key` | `""` | Transport key (auto-derived for PEM) |
| `elasticsearch_transport_tls_key_passphrase` | `""` | Passphrase for encrypted key/P12 |
| `elasticsearch_http_tls_certificate` | `""` | HTTP cert (falls back to transport) |
| `elasticsearch_http_tls_key` | `""` | HTTP key (falls back to transport) |
| `elasticsearch_http_tls_key_passphrase` | `""` | HTTP key passphrase (falls back to transport) |
| `elasticsearch_tls_ca_certificate` | `""` | CA cert (auto-extracted from PEM chain) |
| `elasticsearch_tls_remote_src` | `false` | `true` if cert files are on the managed node |
| `elasticsearch_transport_tls_certificate_content` | `""` | Transport cert as inline PEM string |
| `elasticsearch_transport_tls_key_content` | `""` | Transport key as inline PEM string |
| `elasticsearch_http_tls_certificate_content` | `""` | HTTP cert as inline PEM (falls back to transport) |
| `elasticsearch_http_tls_key_content` | `""` | HTTP key as inline PEM (falls back to transport) |
| `elasticsearch_tls_ca_certificate_content` | `""` | CA cert as inline PEM string |

### Certificate expiry warnings

The role checks certificate expiry on every run. When a certificate is within `elasticsearch_cert_expiration_buffer` days of expiring (default: 30), it emits a warning:

- **Auto-generated certs**: "Run with `--tags renew_es_cert` to renew."
- **External certs**: "Replace the certificate files and re-run the playbook."

### How `elasticsearch_tls_remote_src` works

- `false` (default): Certificate files are on the Ansible controller. The role copies them to each managed node.
- `true`: Certificate files are already on the managed node (e.g., provisioned by cloud-init, Vault agent, certbot). The role copies from one path to another on the same host.

### Migrating from auto-generated to external certificates

When switching an existing cluster from `elasticsearch_ca` to `external`, the role handles the transition automatically:

1. New certificate files are deployed under different names (`<inventory_hostname>-transport.crt` vs the old `<hostname>.p12`), so there is no collision.
2. The `elasticsearch.yml` template switches from P12 keystore/truststore entries to PEM certificate/key entries (or external P12 entries with different paths).
3. Stale P12 keystore and truststore password entries are removed from the Elasticsearch keystore.
4. Old auto-generated `.p12` files are cleaned up from `/etc/elasticsearch/certs/`.
5. Elasticsearch is restarted to pick up the new configuration.

On a multi-node cluster this is an all-at-once operation — all nodes switch cert source in the same playbook run. The role does not support a mixed-cert-source rolling migration where some nodes use the old CA while others use external certs, because the transport layer requires mutual trust between all nodes. Ensure the new external certificates are signed by a CA that all nodes will trust before running the migration.

### Assumptions and auto-detection behaviour

- **Key auto-derivation**: When only a certificate path is provided (PEM format), the role looks for a key file by replacing the certificate extension with `.key`. For example, `/path/to/server.crt` → `/path/to/server.key`. If the derived path doesn't exist, the role fails with a message telling you to set the key variable explicitly.
- **HTTP fallback to transport**: When `elasticsearch_http_tls_certificate` is empty, HTTP reuses the transport cert, key, and passphrase. Set HTTP variables only when transport and API use different certificates.
- **CA chain extraction**: If a PEM certificate file contains multiple certificates (a chain bundle — common with ACME/Let's Encrypt), everything after the first certificate is automatically extracted as the CA chain. If the cert file has only one PEM block and no CA is provided, no `certificate_authorities` entry is configured.
- **SAN validation**: The role checks the certificate's Subject Alternative Names against the node's hostname, FQDN, inventory hostname, and IP addresses. A mismatch produces a warning (not a failure), since wildcard certs and custom verification modes are valid use cases.
