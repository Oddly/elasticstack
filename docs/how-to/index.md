# How To

Task-oriented recipes for common operations, grouped by topic.

## Deployment

- [Kibana behind a reverse proxy](deployment.md#kibana-behind-a-reverse-proxy)
- [Kibana with HTTPS enabled](deployment.md#kibana-with-https-enabled-no-proxy)
- [Kibana with external certificates](deployment.md#kibana-with-external-certificates)
- [Elasticsearch with external certificates](deployment.md#elasticsearch-with-external-certificates)
- [Standalone Logstash (no ES CA)](deployment.md#standalone-logstash-no-elasticsearch-ca)
- [Beats shipping directly to Elasticsearch](deployment.md#beats-shipping-directly-to-elasticsearch)
- [Air-gapped / offline deployment](deployment.md#air-gapped-offline-deployment)

## Cluster Operations

- [Adding a node to an existing cluster](cluster-operations.md#adding-a-node-to-an-existing-elasticsearch-cluster)
- [Dedicated node roles (hot/warm/cold)](cluster-operations.md#dedicated-node-roles-hotwarmcold)
- [Snapshot repository setup](cluster-operations.md#snapshot-repository-setup)

## Configuration

- [`elasticsearch_extra_config` vs `elasticsearch_cluster_settings`](configuration.md#elasticsearch_extra_config-vs-elasticsearch_cluster_settings)
- [`elasticstack_full_stack: false` — when and why](configuration.md#elasticstack_full_stack-false-when-and-why)
- [Simplifying passwords with `elasticstack_cert_pass`](configuration.md#simplifying-passwords-with-elasticstack_cert_pass)
- [Suppressing sensitive output for debugging](configuration.md#suppressing-sensitive-output-for-debugging)

## Pipelines & Inputs

- [Filebeat with multiple log inputs](pipelines.md#filebeat-with-multiple-log-inputs)
- [Logstash with complex pipelines](pipelines.md#logstash-with-complex-pipelines)

## Scaling & High Availability

- [Scaling up (adding nodes)](scaling.md#scaling-up-adding-nodes)
- [Scaling down (removing nodes)](scaling.md#scaling-down-removing-nodes)
- [Multi-Kibana deployment](scaling.md#multi-kibana-deployment)
- [Backup and restore](scaling.md#backup-and-restore)

## Monitoring & Observability

- [Self-monitoring with Beats](monitoring.md#self-monitoring-with-beats)
- [Audit logs](monitoring.md#audit-logs)
- [Health check endpoints](monitoring.md#health-check-endpoints)
