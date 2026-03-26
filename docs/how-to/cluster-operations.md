# Cluster Operations

## Adding a node to an existing Elasticsearch cluster

1. Add the new host to the `elasticsearch` inventory group
2. Run the playbook — the role detects the new node and includes it in `discovery.seed_hosts`
3. The existing cluster auto-accepts the new node because it trusts the same CA

```yaml title="inventory.yml — add es4"
elasticsearch:
  hosts:
    es1: { ansible_host: 10.0.1.10 }
    es2: { ansible_host: 10.0.1.11 }
    es3: { ansible_host: 10.0.1.12 }
    es4: { ansible_host: 10.0.1.13 }   # new node
```

```bash
ansible-playbook -i inventory.yml playbook.yml
```

The CA generates a new certificate for `es4`, distributes it, and the node joins the cluster. Existing nodes are updated with the new `discovery.seed_hosts` list.

!!! note
    If you're adding your first even-numbered master-eligible node (e.g. going from 3 to 4), the role will fail with a quorum warning. Either add the node as data-only (`elasticsearch_node_types: ["data", "ingest"]`) or add two nodes at once to maintain an odd master count.

## Dedicated node roles (hot/warm/cold)

For tiered storage architectures:

```yaml title="host_vars/es-hot1.yml"
elasticsearch_node_types: ["master", "data_hot", "ingest"]
elasticsearch_heap: 16
elasticstack_temperature: hot
```

```yaml title="host_vars/es-warm1.yml"
elasticsearch_node_types: ["data_warm"]
elasticsearch_heap: 8
elasticstack_temperature: warm
```

```yaml title="host_vars/es-cold1.yml"
elasticsearch_node_types: ["data_cold"]
elasticsearch_heap: 4
elasticstack_temperature: cold
```

The `elasticstack_temperature` variable sets `node.attr.temp` in `elasticsearch.yml`, which ILM policies use for data tier routing.

## Snapshot repository setup

Configure filesystem paths for Elasticsearch snapshots:

```yaml title="group_vars/elasticsearch.yml"
elasticsearch_fs_repo:
  - /mnt/backups/elasticsearch
  - /mnt/nfs/snapshots
```

The paths must be accessible from every ES node (typically shared NFS mounts). The role sets `path.repo` in `elasticsearch.yml`. After deployment, create the snapshot repository via Kibana or the API.
