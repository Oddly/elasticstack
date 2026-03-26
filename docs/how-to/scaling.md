# Scaling & High Availability

## Scaling up (adding nodes)

Add hosts to your inventory and re-run:

```yaml title="inventory.yml"
elasticsearch:
  hosts:
    es1: { ansible_host: 10.0.1.10 }
    es2: { ansible_host: 10.0.1.11 }
    es3: { ansible_host: 10.0.1.12 }
    es4: { ansible_host: 10.0.1.13 }   # new
    es5: { ansible_host: 10.0.1.14 }   # new
```

The role generates certificates for new nodes, updates `discovery.seed_hosts` on all nodes, and the new nodes join the cluster automatically.

## Scaling down (removing nodes)

Removing a node requires draining it first:

```bash
# 1. Exclude the node from shard allocation
curl -k -u elastic:PASSWORD -X PUT https://localhost:9200/_cluster/settings -H 'Content-Type: application/json' -d '{
  "persistent": {
    "cluster.routing.allocation.exclude._name": "es5"
  }
}'

# 2. Wait for shards to relocate
watch 'curl -sk -u elastic:PASSWORD https://localhost:9200/_cat/shards?v | grep es5'

# 3. Once no shards remain, remove the node from inventory and re-run
ansible-playbook -i inventory.yml playbook.yml
```

After re-running, clear the allocation exclusion:

```bash
curl -k -u elastic:PASSWORD -X PUT https://localhost:9200/_cluster/settings -H 'Content-Type: application/json' -d '{
  "persistent": {
    "cluster.routing.allocation.exclude._name": null
  }
}'
```

## Multi-Kibana deployment

Run multiple Kibana instances behind a load balancer:

```yaml title="inventory.yml"
kibana:
  hosts:
    kb1: { ansible_host: 10.0.2.10 }
    kb2: { ansible_host: 10.0.2.11 }
```

Both instances connect to the same Elasticsearch cluster. Use `kibana_system_password` to set a consistent password across instances:

```yaml
kibana_system_password: "{{ vault_kibana_password }}"
```

## Backup and restore

### Setting up a snapshot repository

```yaml title="group_vars/elasticsearch.yml"
elasticsearch_fs_repo:
  - /mnt/nfs/es-snapshots
```

After deployment, register the repository and create a snapshot policy:

```bash
# Register the repository
curl -k -u elastic:PASSWORD -X PUT https://localhost:9200/_snapshot/backups -H 'Content-Type: application/json' -d '{
  "type": "fs",
  "settings": { "location": "/mnt/nfs/es-snapshots" }
}'

# Create a daily snapshot policy
curl -k -u elastic:PASSWORD -X PUT https://localhost:9200/_slm/policy/daily-snapshots -H 'Content-Type: application/json' -d '{
  "schedule": "0 30 1 * * ?",
  "name": "<daily-snap-{now/d}>",
  "repository": "backups",
  "config": { "indices": ["*"], "ignore_unavailable": true }
}'
```

### Restoring from a snapshot

```bash
# List available snapshots
curl -k -u elastic:PASSWORD https://localhost:9200/_snapshot/backups/_all?pretty

# Restore specific indices
curl -k -u elastic:PASSWORD -X POST https://localhost:9200/_snapshot/backups/daily-snap-2026.03.26/_restore -H 'Content-Type: application/json' -d '{
  "indices": "logs-*",
  "rename_pattern": "(.+)",
  "rename_replacement": "restored_$1"
}'
```
