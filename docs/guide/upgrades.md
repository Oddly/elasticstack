# Upgrading

## Rolling upgrades from 8.x to 9.x

The Elasticsearch role supports zero-downtime rolling upgrades from Elastic 8.x to 9.x. Each node is stopped, upgraded, and restarted one at a time while the cluster stays operational.

### How it works

1. The role detects the installed version vs the target version
2. For each node (one at a time):
    - Disables shard allocation to prevent rebalancing during restart
    - Flushes indices to reduce recovery time after restart
    - Stops Elasticsearch and upgrades the package
    - Starts Elasticsearch with the new version
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

### Upgrade path requirement

Elasticsearch 9.x requires version 8.19.x as a stepping stone. The role validates this automatically — if you try to jump from 8.15 to 9.x, it fails with a clear error telling you to upgrade to 8.19 first. This is an Elastic requirement, not a role limitation.

### Safety checks

The role refuses to upgrade if:

- The cluster is not green before starting
- The upgrade path requirement is not met (must be on 8.19.x for 9.x)

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
