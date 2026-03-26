# Roles

The collection provides six roles that work together to deploy a complete Elastic Stack. Each role can also be used independently.

| Role | Purpose |
|------|---------|
| [**elasticstack**](elasticstack.md) | Shared defaults inherited by all roles (ports, groups, CA, repos) |
| [**repos**](repos.md) | APT/YUM repository and GPG key setup |
| [**elasticsearch**](elasticsearch.md) | Cluster formation, JVM tuning, security setup, rolling upgrades |
| [**kibana**](kibana.md) | Web UI, Elasticsearch connection, optional HTTPS frontend |
| [**logstash**](logstash.md) | Pipeline management, queue config, ES user/role creation |
| [**beats**](beats.md) | Filebeat, Metricbeat, Auditbeat with syslog, journald, Docker inputs |

## Dependency order

Roles should be applied in this order:

```
repos → elasticsearch → kibana → logstash → beats
```

The `elasticstack` role is included automatically by the others — you don't need to call it directly unless you want to override its defaults.
