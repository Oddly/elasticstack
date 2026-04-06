# Changelog

## 0.1.0 (unreleased)

First release of the `oddly.elasticstack` collection, forked from
[NETWAYS/ansible-collection-elasticstack](https://github.com/NETWAYS/ansible-collection-elasticstack).

### Highlights

- Full Elastic Stack 9.x support alongside 8.x, with version-aware templates
  that switch configuration syntax automatically.
- Rolling upgrades from 8.x to 9.x with upgrade path validation, per-node
  orchestration, and shard allocation management.
- Complete TLS PKI: CA generation, per-node certificates, automatic renewal,
  and support for external certificates (PEM and PKCS12) with format
  auto-detection.
- Inline PEM content variables for Vault / secrets manager integration
  (Elasticsearch, Kibana, Beats).
- Separate transport and HTTP layer certificates on Elasticsearch.
- Certificate expiry warnings and tag-driven renewal (`--tags certificates`,
  `--tags renew_es_cert`, `--tags renew_ca`).
- Logstash standalone certificate mode for independent deployments.
- Beats Filebeat `filestream` input type for 9.x (replacing deprecated `log`).
- Logstash `elastic_agent` input plugin support.
- Elasticsearch `cluster_settings` for runtime cluster configuration via API.
- LogsDB support with automatic enablement on fresh 9.x installs.
- Elasticsearch filesystem snapshot repository configuration.
- Cgroup-aware JVM heap auto-calculation for containerised deployments.
- Container workarounds: systemd `Type=exec` override, lenient disk watermarks.
- `elasticsearch_extra_config`, `kibana_extra_config`, `logstash_extra_config`
  for arbitrary YAML settings without dedicated variables.
- `elasticstack_cert_pass` shortcut to set all TLS key passphrases at once.
- MkDocs Material documentation site with task flow diagrams, TLS guide, and
  recipes.

### Supported platforms

- Debian 12 (bookworm), 13 (trixie)
- Ubuntu 22.04 (jammy), 24.04 (noble), 26.04 (resolute)
- Rocky Linux / RHEL 9, 10
- Elastic Stack 8.x and 9.x
- Ansible 2.18+

### Breaking changes from netways.elasticstack

- Namespace changed from `netways` to `oddly`.
- Minimum Ansible version raised to 2.18 (was 2.9).
- Debian 10/11 and Ubuntu 20.04 dropped from supported platforms.
- `elasticsearch_security: false` no longer permitted on ES 8.x+ (Elastic
  upstream requirement).
- Logstash `logstash_beats_tls` renamed to `logstash_input_beats_ssl` (old name
  still accepted for backwards compatibility).
