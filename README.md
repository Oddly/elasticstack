# oddly.elasticstack

An Ansible collection for deploying and managing the Elastic Stack (Elasticsearch, Kibana, Logstash, Beats) on Debian, Ubuntu, and RHEL/Rocky Linux. Forked from [NETWAYS/ansible-collection-elasticstack](https://github.com/NETWAYS/ansible-collection-elasticstack) with Elastic 9.x support, rolling upgrades, and full TLS certificate lifecycle management.

## Install

```bash
ansible-galaxy collection install oddly.elasticstack
```

Requires Ansible 2.18+ and the `community.general` collection.

## Quick start

```yaml
# inventory.yml
all:
  children:
    elasticsearch:
      hosts:
        es1: { ansible_host: 10.0.1.10 }
        es2: { ansible_host: 10.0.1.11 }
        es3: { ansible_host: 10.0.1.12 }
    kibana:
      hosts:
        kb1: { ansible_host: 10.0.1.20 }
    logstash:
      hosts:
        ls1: { ansible_host: 10.0.1.30 }

# playbook.yml
- hosts: all
  vars:
    elasticstack_release: 9
    elasticstack_full_stack: true
  roles:
    - oddly.elasticstack.repos
    - oddly.elasticstack.elasticsearch
    - oddly.elasticstack.kibana
    - oddly.elasticstack.logstash
    - oddly.elasticstack.beats
```

Roles must run in this order. Each role uses inventory group names (`elasticsearch`, `logstash`, `kibana`) to discover other services and delegates certificate operations to the first Elasticsearch host.

After the run, initial passwords are in `/usr/share/elasticsearch/initial_passwords` on the first ES host.

## Supported platforms

- Debian 11, 12, 13
- Ubuntu 22.04, 24.04
- Rocky Linux / RHEL 8, 9, 10
- Elastic Stack 8.x and 9.x

## Documentation

The **[Wiki](https://github.com/Oddly/elasticstack/wiki)** has full documentation:

- [Getting Started](https://github.com/Oddly/elasticstack/wiki/Getting-Started) -- walkthrough for single-node and multi-node deployments
- [Architecture](https://github.com/Oddly/elasticstack/wiki/Architecture) -- data flow, TLS PKI, security init, rolling upgrades, retry budgets
- [elasticsearch](https://github.com/Oddly/elasticstack/wiki/Roles-elasticsearch) -- cluster formation, JVM tuning, security setup, rolling upgrades
- [kibana](https://github.com/Oddly/elasticstack/wiki/Roles-kibana) -- web UI, ES connection, optional HTTPS frontend
- [logstash](https://github.com/Oddly/elasticstack/wiki/Roles-logstash) -- pipelines, queue config, ES user/role creation
- [beats](https://github.com/Oddly/elasticstack/wiki/Roles-beats) -- Filebeat, Metricbeat, Auditbeat with syslog, journald, Docker inputs
- [elasticstack](https://github.com/Oddly/elasticstack/wiki/Roles-elasticstack) -- shared defaults (ports, groups, CA, repos)
- [repos](https://github.com/Oddly/elasticstack/wiki/Roles-repos) -- APT/YUM repository setup

## License

GPL-3.0-or-later
