Collection Elastic Stack
-------------------------

Installation
-----------

You can easily install the collection with the ansible-galaxy command.

```
ansible-galaxy collection install oddly.elasticstack
```

Or if you are using Tower or AWX add the collection to your requirements file.

```
collections:
  - name: oddly.elasticstack
```

Usage
---------

To use the collection in your Ansible playbook add the following key to your playbook.

```
- name: Playbook
  hosts: some_host_pattern
  collections:
    - oddly.elasticstack
  tasks:
    - name: import role logstash
      import_role:
        name: logstash
```

Or refer to the role with the FQCN of the role.

```
- name: Playbook
  hosts: some_host_pattern
  tasks:
    - name: import role by FQCN  from a collection
      import_role:
        name: oddly.elasticstack.logstash
```

Roles
-------

* [Beats](role-beats.md)
* [Elasticsearch](role-elasticsearch.md)
* [Kibana](role-kibana.md)
* [Logstash](role-logstash.md)
* [Repos](role-repos.md)


Variables
-----------

Every role got its own set of variables, in addition a few variables are useable on any role. Below are all general collection vars.

* *elasticstack_release*: Major release version of Elastic stack to configure. (default: `8`). Supported values: `7`, `8`, `9`. For upgrading to 9.x, see the [Elasticsearch 9.x Upgrade Guide](./elasticsearch-9x-upgrade.md).
* *elasticstack_variant*: Variant of the stack to install. Valid values: `elastic` or `oss`. (default: `elastic`). Note: OSS variant is only available for version 7.x.
