# Upgrading

## Rolling upgrades from 8.x to 9.x

The Elasticsearch role supports zero-downtime rolling upgrades from Elastic 8.x to 9.x. Each node is stopped, upgraded, and restarted one at a time while the cluster stays operational.

### How it works

1. The role detects the installed version vs the target version
2. For each node (one at a time):
    - Disables shard allocation to prevent rebalancing during restart
    - Synced-flushes (8.x) or flushes (9.x) to minimize recovery time
    - Stops Elasticsearch
    - Upgrades the package to the target version
    - Starts Elasticsearch
    - Waits for the node to rejoin and the cluster to reach green
    - Re-enables shard allocation
3. Kibana, Logstash, and Beats are upgraded after Elasticsearch

### Running an upgrade

Change the release version and re-run your playbook:

```yaml title="group_vars/all.yml"
elasticstack_release: 9   # was 8
```

```bash
ansible-playbook -i inventory.yml playbook.yml
```

The role handles the upgrade order automatically. Elasticsearch nodes are upgraded first, then Kibana, Logstash, and Beats.

### Safety checks

The role refuses to upgrade if:

- The cluster is not green (all primary and replica shards assigned)
- There are unassigned shards that could indicate data loss
- The target version is more than one major version ahead

### Unsafe restart mode

For development environments where you want to skip the safety checks:

```yaml
elasticsearch_unsafe_upgrade_restart: true
```

!!! warning
    Never use this in production. It bypasses the rolling upgrade safety checks and may cause data loss.

### Upgrading other components

Kibana, Logstash, and Beats are simpler — they don't need rolling restarts. The roles detect the version mismatch, upgrade the package, and restart the service. Run them after all Elasticsearch nodes are upgraded.

### Rollback

There is no automated rollback. If an upgrade fails:

1. Stop Elasticsearch on the failed node
2. Downgrade the package: `apt install elasticsearch=8.x.y` or `yum downgrade elasticsearch-8.x.y`
3. Start Elasticsearch
4. The node will rejoin the cluster with the old version

!!! note
    Elasticsearch does not support running mixed major versions long-term. Complete the upgrade or roll back all nodes to the same version.

## Minor version upgrades

Minor version upgrades (e.g. 8.15 to 8.17) are handled automatically. Re-run the playbook and the package manager installs the latest version within the major release. No special steps needed — the role handles service restart and health checks.
