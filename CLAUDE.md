# ansible-collection-elasticstack - LLM Development Guide

Ansible collection (`oddly.elasticstack`) for installing and managing the Elastic Stack. Fork of NETWAYS/ansible-collection-elasticstack with Elasticsearch 9.x support.

## Tech Stack

- **Ansible**: Collection with roles, modules, and module_utils
- **Molecule**: Integration testing with Docker containers
- **Python**: Custom Ansible modules and unit tests

## Structure

```
├── roles/
│   ├── beats/           # Filebeat, Metricbeat, Auditbeat
│   ├── elasticsearch/   # Elasticsearch installation and configuration
│   ├── elasticstack/    # Shared stack utilities (versions, passwords)
│   ├── kibana/          # Kibana installation and configuration
│   ├── logstash/        # Logstash with pipeline management
│   └── repos/           # APT/YUM repository setup
├── plugins/
│   ├── modules/         # elasticsearch_role, elasticsearch_user, cert_info
│   └── module_utils/    # Shared Python utilities (api.py, certs.py)
├── molecule/            # Integration test scenarios
│   ├── elasticsearch_default/
│   ├── elasticstack_default/
│   ├── kibana_default/
│   ├── beats_default/
│   ├── logstash_pipelines/
│   └── ...              # ~15 scenarios total
├── tests/unit/          # Python unit tests for modules
├── docs/                # Role and module documentation
└── galaxy.yml           # Collection metadata (namespace: oddly, name: elasticstack)
```

## Commands

```bash
# Linting
make ansible-lint
make yamllint
ansible-lint ./roles/*
yamllint .

# Unit tests
python -m pytest tests/unit/

# Molecule integration tests
molecule test -s elasticsearch_default
molecule test -s elasticstack_default
molecule test -s kibana_default
molecule test -s beats_default
molecule converge -s <scenario>    # Run without destroy
molecule verify -s <scenario>      # Run verification only

# Build collection
ansible-galaxy collection build
ansible-galaxy collection install oddly-elasticstack-*.tar.gz
```

## Key Patterns

- Each role has `defaults/main.yml` with all configurable variables
- Platform-specific vars in `vars/Debian.yml` and `vars/RedHat.yml`
- Molecule scenarios use `geerlingguy/docker-*-ansible` images
- Security tasks are separated into `*-security.yml` task files
- Jinja2 templates for config files (elasticsearch.yml, kibana.yml, etc.)

## Documentation

Comprehensive docs in `docs/`:
- `getting-started.md` - Quick start guide
- `role-elasticsearch.md`, `role-kibana.md`, etc. - Per-role variable reference
- `module-elasticsearch_role.md`, `module-elasticsearch_user.md` - Module docs
