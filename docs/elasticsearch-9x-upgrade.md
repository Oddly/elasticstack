# Elasticsearch 9.x Upgrade Guide

This document covers the requirements and considerations for upgrading to Elasticsearch 9.x using the NETWAYS Ansible collection.

## Upgrade Path Requirements

### Prerequisites

| Current Version | Target Version | Required Intermediate Step |
|-----------------|----------------|---------------------------|
| 8.17.x or earlier | 9.0.x | Upgrade to **8.18.x** first |
| 8.18.x | 9.0.x | Direct upgrade supported |
| 8.18.x or earlier | 9.1.x+ | Upgrade to **8.19.x** first |
| 8.19.x | 9.1.x+ | Direct upgrade supported |

### Critical Pre-Upgrade Steps

1. **Run the Upgrade Assistant** in Kibana to identify deprecations and blockers
2. **Handle indices created in 7.x**: Must be reindexed, deleted, or marked as read-only
3. **Review and remove deprecated settings** from `elasticsearch.yml`
4. **Create a snapshot backup** before upgrading

## Rolling Upgrade Procedure

The NETWAYS collection supports rolling upgrades. The procedure is:

1. **Upgrade data nodes first** (one at a time)
2. **Upgrade master nodes last** (one at a time)
3. Each node: stop → upgrade packages → start → wait for green/yellow

### Important Notes

- Running multiple ES versions in the same cluster is only supported during the upgrade window
- New functionality is disabled until ALL nodes are upgraded
- Once upgraded, older nodes cannot rejoin the cluster

## Breaking Changes in Elasticsearch 9.0

### Removed Settings

These settings were deprecated and are now removed in 9.x:

| Setting | Notes |
|---------|-------|
| `cluster.routing.allocation.disk.watermark.enable_for_single_data_node` | Use standard watermark settings |
| `node.max_local_storage_nodes` | Was already ignored |
| `_cluster_setting_override` | Internal setting removed |
| `snapshot.storage.data_on_rolling_restart` | Removed |
| Deprecated telemetry `.*` settings | Use `telemetry.*` equivalents |

### Settings Only Valid for ES 7.x (Already Handled)

These settings are only applied for ES 7.x in our templates:

| Setting | ES 7 | ES 8 | ES 9 |
|---------|------|------|------|
| `bootstrap.system_call_filter` | Yes | No | No |
| `xpack.monitoring.collection.enabled` | Yes | No | No |

### Removed API Features

- Deprecated `local` attribute removed from alias APIs
- Legacy parameters removed from range query
- Support for `type`, `fields`, `copy_to`, `boost` in metadata field definitions removed
- `data_frame_transforms` roles removed
- Old `_knn_search` tech preview API removed

### Security Changes

- TLS_RSA cipher support dropped for JDK 24
- Certificate-based remote cluster security model deprecated

## Python Client Compatibility

The `elasticsearch-py` library has breaking changes between 8.x and 9.x:

### Parameter Renames

| Old (8.x) | New (9.x) |
|-----------|-----------|
| `timeout` | `request_timeout` |
| `randomize_hosts` | `randomize_nodes_in_pool` |
| `sniffer_timeout` | `min_delay_between_sniffing` |
| `sniff_on_connection_fail` | `sniff_on_node_failure` |
| `maxsize` | `connections_per_node` |
| `url_prefix` | `path_prefix` |

### Removed Parameters

- `use_ssl` - Now inferred from URL scheme (`https://`)

### Our Approach

The NETWAYS collection uses runtime detection to support both client versions:

```python
import elasticsearch
ES_CLIENT_VERSION = int(elasticsearch.__version__.split('.')[0])

if ES_CLIENT_VERSION >= 9:
    # Use 9.x compatible parameters
else:
    # Use 8.x compatible parameters
```

## Cluster Architecture Considerations

### Single-Node Clusters

- Simplest upgrade path
- No rolling upgrade needed - just stop, upgrade, start
- `discovery.type: single-node` continues to work in 9.x

### Multi-Node Clusters

- Rolling upgrade required for zero-downtime
- Data nodes should be upgraded before master nodes
- Ensure you have an odd number of master-eligible nodes

### Dedicated Master Nodes

- Upgrade master nodes last
- Never upgrade more than one master at a time
- Wait for cluster to stabilize between each master upgrade

## Testing Matrix

The collection is tested with the following scenarios:

| Scenario | ES Version | Nodes | Description |
|----------|------------|-------|-------------|
| Fresh install single | 9.x | 1 | New single-node deployment |
| Fresh install cluster | 9.x | 3 | New multi-node cluster |
| Upgrade single | 8.x → 9.x | 1 | Single-node upgrade |
| Upgrade cluster | 8.x → 9.x | 3 | Rolling cluster upgrade |

## Kibana, Logstash, and Beats

### Upgrade Order

1. Elasticsearch (all nodes)
2. Kibana
3. Logstash
4. Beats

### Version Compatibility

- Kibana must match ES major version
- Logstash 9.x required for ES 9.x
- Beats 9.x recommended for ES 9.x (8.x may work with compatibility mode)

## Troubleshooting

### Common Issues

#### "Index created in older version" Error

```
Indices created in version 7.x must be reindexed or deleted before upgrading to 9.x
```

**Solution**: Use the Upgrade Assistant or manually reindex/delete affected indices.

#### Python Client Version Mismatch

```
elasticsearch.exceptions.UnsupportedProductError
```

**Solution**: Ensure the Python client version matches your ES server version.

#### Deprecated Settings in Config

```
unknown setting [xpack.monitoring.collection.enabled]
```

**Solution**: Remove deprecated settings from `elasticsearch.yml` before upgrading.

## References

- [Elastic Upgrade Documentation](https://www.elastic.co/docs/deploy-manage/upgrade)
- [ES 9.x Breaking Changes](https://www.elastic.co/docs/release-notes/elasticsearch/breaking-changes)
- [Python Client Migration](https://elasticsearch-py.readthedocs.io/)
