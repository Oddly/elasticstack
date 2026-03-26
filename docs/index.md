# oddly.elasticstack

An Ansible collection for deploying and managing the Elastic Stack — Elasticsearch, Kibana, Logstash, and Beats — on Debian, Ubuntu, and RHEL/Rocky Linux.

```yaml
# Install
ansible-galaxy collection install oddly.elasticstack

# Deploy a 3-node cluster with Kibana
- hosts: all
  vars:
    elasticstack_release: 9
    elasticstack_full_stack: true
  roles:
    - oddly.elasticstack.repos
    - oddly.elasticstack.elasticsearch
    - oddly.elasticstack.kibana
```

## Features

- **Full lifecycle management** — from repository setup through rolling upgrades
- **Automatic TLS** — generates and distributes certificates for inter-node and HTTP encryption
- **Security bootstrapping** — creates users, roles, and passwords on first run
- **Rolling upgrades** — 8.x to 9.x with zero-downtime node-by-node upgrades
- **Multi-platform** — Debian 11-13, Ubuntu 22.04/24.04, Rocky Linux/RHEL 8-10

<div class="grid cards" markdown>

- :material-rocket-launch: **[Getting Started](introduction/getting-started.md)**

    Install the collection and deploy your first cluster in minutes.

- :material-map: **[Guide](guide/index.md)**

    Understand the architecture, TLS model, and how the roles work together.

- :material-book-open-variant: **[Reference](reference/index.md)**

    Every variable, default, and option for each role.

- :material-wrench: **[How To](how-to/index.md)**

    Task-oriented recipes for common operations.

- :material-frequently-asked-questions: **[FAQ](faq.md)**

    Answers to common questions and troubleshooting tips.

</div>
