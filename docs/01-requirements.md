# Requirements

There are some requirements to keep in mind when using this collection.

**Inventory groups**

The collection uses inventory group names to discover which hosts run which services. The default group names are `elasticsearch`, `logstash`, and `kibana`. You can override them with these variables:

- `elasticstack_elasticsearch_group_name` (default: `elasticsearch`)
- `elasticstack_logstash_group_name` (default: `logstash`)
- `elasticstack_kibana_group_name` (default: `kibana`)

Hosts must be in the correct groups for cross-role features like certificate generation and password distribution to work.

**elasticstack_ca_host**

This variable defines which host acts as the Certificate Authority for TLS certificates. It defaults to the first host in the `elasticsearch` group. If no `elasticsearch` group exists (e.g. standalone Kibana or Beats deployments), it falls back to `inventory_hostname`. You can override it explicitly if needed.

**Supported versions**

The collection supports Elastic Stack 8.x and 9.x. Set `elasticstack_release` to `8` or `9` (default: `8`). See the [Elasticsearch 9.x Upgrade Guide](./elasticsearch-9x-upgrade.md) for upgrade instructions.
