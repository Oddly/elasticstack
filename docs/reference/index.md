# Reference

Complete variable reference for each role in the collection. Every role can be used independently or as part of a coordinated full-stack deployment.

| Role | Purpose |
|------|---------|
| [**elasticstack**](elasticstack.md) | Shared defaults inherited by all roles (ports, groups, CA, repos) |
| [**repos**](repos.md) | APT/YUM repository and GPG key setup |
| [**elasticsearch**](elasticsearch.md) | Cluster formation, JVM tuning, security setup, rolling upgrades |
| [**kibana**](kibana.md) | Web UI, Elasticsearch connection, optional HTTPS frontend |
| [**logstash**](logstash.md) | Pipeline management, queue config, ES user/role creation |
| [**beats**](beats.md) | Filebeat, Metricbeat, Auditbeat with syslog, journald, Docker inputs |
| [**elastic_agent**](elastic_agent.md) | Standalone Agent policies, Fleet enrollment, Fleet Server, and Beats migration |

## Dependency order

Roles should be applied in this order:

```text
repos → elasticsearch → kibana → logstash → beats / elastic_agent
```

The `elasticstack` role is included automatically by the others — you don't need to call it directly unless you want to override its defaults.
