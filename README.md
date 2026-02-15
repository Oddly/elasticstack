# Ansible Collection - oddly.elasticstack

![Test ElasticStack](https://github.com/Oddly/elasticstack/actions/workflows/test_full_stack.yml/badge.svg)

This collection installs and manages the Elastic Stack. It provides roles for every component of the Stack. Originally based on [netways.elasticstack](https://github.com/NETWAYS/elasticstack), with ES 9.x support, a rewritten Logstash role, modular certificate handling, and dual-platform CI.

Every role is documented with all variables, please refer to the documentation found in **[Getting-Started](./docs/getting-started.md)**

**Please note**: If you are already using this collection before version `1.0.0`, please note that we had to rename a significant amount of variables due to naming schema changes made by Ansible. Please review the variables you have set in your playbooks and variable files.

## Roles documentation

> [!NOTE]
> Some roles have requirements that you must observe. Please have a look at the [requirements](docs/01-requirements.md) before using the collection.

* [Beats](docs/role-beats.md)
* [Elasticsearch](docs/role-elasticsearch.md)
* [Kibana](docs/role-kibana.md)
* [Logstash](docs/role-logstash.md)
* [Repos](docs/role-repos.md)

## Modules documentation

* [elasticsearch_role](docs/module-elasticsearch_role.md)
* [elasticsearch_user](docs/module-elasticsearch_user.md)

## Global variables

* `elasticstack_force_pip`: Will force installation of required Python modules via `pip`. This is useful if your package manager doesn't provide current versions of modules. (Default: `false`) See [PEP668](https://peps.python.org/pep-0668/) for more details.
* `elasticstack_manage_pip`: Will install `pip` on your system. (Default: `false`)

## Installation

You can easily install the collection with the `ansible-galaxy` command.

```
ansible-galaxy collection install git+https://github.com/Oddly/elasticstack.git
```

Or if you are using Tower or AWX add the collection to your requirements file.

```
collections:
  - name: oddly.elasticstack
```

### Requirements

You will need the following Ansible collections installed

* `community.general` (probably already present)

You will need these packages / libraries installed. Some very basic packages like `openssl` get handled by the collection if needed. The following list contains packages and libraries which only apply to special cases or need for you to decide on the installation method.

* `passlib` Python library if you do not disable password hashing for logstash user and you want to use logstash role from this collection. It should be installed with pip on the Ansible controller.
* `elasticsearch` Python module (version 8.x or 9.x). See the [Python Client Compatibility](#python-client-compatibility) section below for upgrade guidance.

You may want the following Ansible roles installed. There other ways to achieve what they are doing but using them is easy and convenient.

* `geerlingguy.redis` if you want to use logstash role

### Supported systems

We test the collection on the following Linux distributions. Each one with Elastic Stack 8 and 9.

* Rocky Linux 10
* Rocky Linux 9
* Rocky Linux 8
* Ubuntu 24.04 LTS
* Ubuntu 22.04 LTS
* Debian 13
* Debian 12
* Debian 11

> **Note**: Elastic Stack 9.x support is available starting with this version of the collection. See the [Elasticsearch 9.x Upgrade Guide](./docs/elasticsearch-9x-upgrade.md) for upgrade instructions.

### Known Issues


### Python Client Compatibility

The `elasticsearch` Python library follows specific compatibility rules with Elasticsearch servers:

| Client Version | ES 8.x Server | ES 9.x Server |
|---------------|---------------|---------------|
| elasticsearch 8.x | ✅ Full support | ✅ Forward compatible |
| elasticsearch 9.x | ❌ Will not work | ✅ Full support |

**Key points:**
- The 8.x client is **forward compatible** with ES 9.x servers (works, but without new 9.x features)
- The 9.x client is **NOT backward compatible** with ES 8.x servers (will fail immediately)

**Upgrade path (ES 8.x → 9.x):**
1. **Before upgrading ES:** Keep using `pip install 'elasticsearch>=8,<9'`
2. **Upgrade ES server** to 9.x (the 8.x client continues to work)
3. **After ES upgrade (optional):** Upgrade to `pip install 'elasticsearch>=9,<10'` for full 9.x feature support

The collection includes a `Api.check_version_compatibility()` method that validates client/server compatibility and provides actionable guidance.

## Usage

Every role is documented with all variables, please refer to the documentation found in **[Getting-Started](./docs/getting-started.md)**

Make sure all hosts that should be configured are part of your playbook. (See below for details on groups etc.). The collection is built to first collect all facts from all hosts (including those only running beats) and then use facts like hostnames or ip addresses to connect the tools to each other.

You will want to have reliable DNS resolution or enter all hosts of the stack into your systems hosts files.

The variable `elasticstack_no_log` can be set to `false` if you want to see the output of all tasks. It defaults to `true` because some tasks could reveal passwords in production.

### Versions and upgrades

*elasticstack_version*: Version number of tools to install. Only set if you don't want the latest on new setups. (default: none). If you already have an installation of Elastic Stack, this collection will query the version of Elasticsearch on the CA host and use it for all further installations in the same setup. (Only if you run the `elasticsearch` role before all others) Example: `8.19.0`

*elasticstack_release*: Major release version of Elastic stack to configure. (default: `8`) Make sure it corresponds to `elasticstack_version` if you set both. Supported values: `8`, `9`.

```yaml
roles:
   - role: oddly.elasticstack.kibana
     vars:
        elasticstack_version: 8.7.1
   - role: oddly.elasticstack.elasticsearch
     vars:
        elasticstack_version: 8.8.1
```

#### Upgrades ####

Set `elasticstack_version` to the version you want to upgrade to. Positively do read and understand Elastics changelog and "breaking changes" of your target version and all between your current and the target version. Do not use unless you have a valid backup.

**Upgrading to Elasticsearch 9.x**: See the [Elasticsearch 9.x Upgrade Guide](./docs/elasticsearch-9x-upgrade.md) for detailed requirements and considerations. Key points:
- You must upgrade to 8.18.x or 8.19.x before upgrading to 9.x
- Old 7.x indices must be reindexed or deleted before upgrading
- Run the Upgrade Assistant in Kibana to identify deprecation warnings

If an upgrade fails, you can try re-running the collection with the same settings. There are several tasks that can provide "self-healing". Please do not rely on these mechanisms, they are more of a "convenience recovery" for easier steps.

The collection will make sure to upgrade Elasticsearch nodes one by one.

### Default Passwords

Default passwords can be seen during generation, or found later in `/usr/share/elasticsearch/initial_passwords`

To turn off security:

`elasticstack_override_beats_tls: true`

### Requirements

0) You need to install the redis role which is maintained by geerlingguy.

```
ansible-galaxy install geerlingguy.redis
```

1) Default: For general Elastic Stack installations using all features use the following. You will need Redis installed and running for the default setup to run. A viable way is using the `geerlingguy.redis` role.

Our default configuration will collect filesystem logs placed by `rsyslog`. Therefor our example playbook makes sure, `rsyslog` is installed. If you don't want that, please change the configuration of the `beats` module. Without syslog you won't receive any messages with the default configuration.

There are some comments in the Playbook. Either fill them with the correct values (`remote_user`) or consider them as a hint to commonly used options.

### Inventory

_Note_: The roles rely on group names for placing services on hosts. Please make sure you have group names defined: `elasticstack_elasticsearch_group_name` (default: `elasticsearch`), `elasticstack_logstash_group_name` (default: `logstash`) and `elasticstack_kibana_group_name` (default: `kibana`) that will match your desired setup in your Ansible inventory. Hosts in these groups will get the respective services. Just restricting your plays to the appropriate hosts will not work because the roles interact with hosts from other groups e.g. for certificate generation.

The execution order of the roles is important! (see below)

```yaml
---
- hosts: all
  become: true
  vars:
    elasticstack_release: 9
  roles:
    - oddly.elasticstack.repos

- hosts: elasticsearch
  become: true
  vars:
    elasticsearch_jna_workaround: true
  roles:
    - oddly.elasticstack.elasticsearch

- hosts: logstash
  become: true
  vars:
    elasticstack_override_beats_tls: true
  roles:
    - geerlingguy.redis
    - oddly.elasticstack.logstash

- hosts: kibana
  become: true
  roles:
    - oddly.elasticstack.kibana

- hosts: all
  become: true
  vars:
    elasticstack_override_beats_tls: true
  pre_tasks:
    - name: Install Rsyslog
      ansible.builtin.package:
        name: rsyslog
    - name: Start rsyslog
      ansible.builtin.service:
        name: rsyslog
        state: started
        enabled: true
  roles:
    - oddly.elasticstack.beats
```

## Contributing

Every kind of contribution is very welcome. Open [issues](https://github.com/Oddly/elasticstack/issues) or provide [pull requests](https://github.com/Oddly/elasticstack/pulls).

Please note that we have some actions bound to specific names of branches. So please stick to the following naming scheme:

* `fix/` as a prefix for every branch that fixes a problem
* `feature/` for every branch that enhances the code with new features
* `doc/` as a prefix for every branch that only changes documentation

For now we open pull requests against `main`. We are planning to introduce dedicated branches to support older versions without breaking changes. Since we don't need them for now, please check back with this section because when we decided on how to proceed, you will find the information here. For now `main` always has the newest changes and if you want a stable version, please use the newest release.

## Testing

Besides real tests that the developer should do before creating a PR, we built molecule scenarios to test the complete stack.
In parallel, we check for ansible and yaml lint errors. To do this pro-actively, a `makefile` is included. You can use this by calling `make`.
