# FAQ

## General

### Which Elastic Stack versions are supported?

8.x and 9.x. Set `elasticstack_release: 9` (or `8`) to choose. The default is `8`.

### Can I use this collection with AWX or Ansible Tower?

Yes. The collection uses standard Ansible modules and works with any Ansible controller. Make sure the controller can SSH to the target hosts and that the collection is installed in the controller's collections path.

### Do I need to apply all roles, or can I use them individually?

Each role works independently. You can install just Elasticsearch, or just Beats, without the other components. The `elasticstack` shared-defaults role is included automatically by the others.

## Elasticsearch

### How is the JVM heap sized?

The Elasticsearch role detects cgroup memory limits (for containers) and physical RAM. It calculates heap as `min(RAM/2, 30GB)` with a minimum of 1GB. Override with `elasticsearch_heap: "4"` (in GB).

### What happens during a rolling upgrade from 8.x to 9.x?

The role stops each node one at a time, upgrades the package, starts the node, and waits for the cluster to return to green before proceeding to the next node. Set `elasticstack_release: 9` and re-run the playbook.

### How do I add a custom keystore entry?

Use `elasticsearch_keystore_entries`:

```yaml
elasticsearch_keystore_entries:
  xpack.notification.slack.account.monitoring.secure_url: "https://hooks.slack.com/services/T00/B00/XXX"
```

Values are passed via stdin and never appear in logs. See the [Elasticsearch reference](reference/elasticsearch.md).

## TLS & Certificates

### Where are certificates stored?

On each node at `/etc/elasticsearch/certs/`, `/etc/kibana/certs/`, etc. The CA private key lives only on the CA host (first node in the `elasticsearch` group by default).

### Can I bring my own certificates?

Yes. Set `elasticsearch_cert_source: external` and provide paths to your certificate, key, and CA files. See [TLS & Certificates](guide/tls.md).

### How do I renew certificates?

Re-run the playbook. The roles detect expiring certificates and regenerate them. For a forced renewal, delete the existing certificates from the target hosts first.

## Kibana

### How do I set a custom `kibana_system` password?

Set `kibana_system_password` in your playbook vars. The role changes the password via the Elasticsearch security API and configures Kibana to use it. See the [Kibana reference](reference/kibana.md).

## Troubleshooting

### Elasticsearch won't start after an upgrade

Check `/var/log/elasticsearch/` for errors. Common causes: incompatible JVM options (the role handles this), insufficient disk space, or a node that was removed from the cluster during the upgrade.

### Kibana shows "Kibana server is not ready yet"

Kibana waits for Elasticsearch to be available. Check that Elasticsearch is running and healthy (`curl -k https://localhost:9200/_cluster/health`), and that Kibana can reach it (check `elasticsearch.hosts` in `/etc/kibana/kibana.yml`).

### Ansible fails with "No module named 'cryptography'"

Install `python3-cryptography` on the target hosts, or add it to your requirements: `pip install cryptography`. The collection needs it for certificate operations.
