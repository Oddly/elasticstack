#!/usr/bin/python

# Copyright (c) 2024, Tobias Bauriedel <tobias.bauriedel@netways.de>
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or
# https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r'''
---
module: elasticsearch_role
short_description: Manage Elasticsearch roles
version_added: "1.0.0"
description:
    - Create, update, and delete Elasticsearch security roles.
    - Requires the Elasticsearch Python client library.
options:
    name:
        description: Name of the Elasticsearch role.
        required: true
        type: str
    cluster:
        description: List of cluster privileges for the role.
        required: false
        type: list
        elements: str
    indices:
        description:
            - List of index privilege objects for the role.
            - Each object should contain C(names) and C(privileges) keys.
        required: false
        type: list
        elements: dict
        aliases: ['indicies']
    state:
        description: Whether the role should be present or absent.
        required: false
        type: str
        default: present
        choices: ['present', 'absent']
    host:
        description: Elasticsearch host URL.
        required: true
        type: str
    auth_user:
        description: Username for Elasticsearch authentication.
        required: true
        type: str
    auth_pass:
        description: Password for Elasticsearch authentication.
        required: true
        type: str
        no_log: true
    ca_certs:
        description: Path to a CA certificate file for SSL verification.
        required: false
        type: str
    verify_certs:
        description: Whether to verify SSL certificates.
        required: false
        type: bool
        default: true
author:
    - Tobias Bauriedel (@tobiasbauriedel)
'''

EXAMPLES = r'''
- name: Create a role with cluster and index privileges
  oddly.elasticstack.elasticsearch_role:
    name: my-role
    cluster:
      - manage_own_api_key
    indices:
      - names:
          - my-index-*
        privileges:
          - read
          - write
    state: present
    host: https://localhost:9200
    auth_user: elastic
    auth_pass: changeme
    verify_certs: false

- name: Delete a role
  oddly.elasticstack.elasticsearch_role:
    name: my-role
    state: absent
    host: https://localhost:9200
    auth_user: elastic
    auth_pass: changeme
    verify_certs: false
'''

RETURN = r'''
msg:
    description: A message describing what action was taken.
    returned: changed
    type: str
    sample: "my-role has been created"
diff:
    description: Before and after state when running with --diff.
    returned: changed and diff mode
    type: dict
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.oddly.elasticstack.plugins.module_utils.elasticsearch_role import (
    Role
)


def run_module():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            cluster=dict(type='list', required=False, elements='str'),
            indices=dict(type='list', required=False, elements='dict',
                         aliases=['indicies']),
            state=dict(type='str', required=False, default='present',
                       choices=['present', 'absent']),
            host=dict(type='str', required=True),
            auth_user=dict(type='str', required=True),
            auth_pass=dict(type='str', required=True, no_log=True),
            ca_certs=dict(type='str', required=False),
            verify_certs=dict(type='bool', required=False, default=True),
        ),
        supports_check_mode=True,
    )

    role = Role(
        module=module,
        role_name=module.params['name'],
        cluster=module.params['cluster'],
        indices=module.params['indices'],
        state=module.params['state'],
        host=module.params['host'],
        auth_user=module.params['auth_user'],
        auth_pass=module.params['auth_pass'],
        ca_certs=module.params['ca_certs'],
        verify_certs=module.params['verify_certs'],
    )

    result = role.return_result()
    module.exit_json(**result)


if __name__ == "__main__":
    run_module()
