#!/usr/bin/python

# Copyright (c) 2024, Tobias Bauriedel <tobias.bauriedel@netways.de>
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or
# https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r'''
---
module: elasticsearch_user
short_description: Manage Elasticsearch users
version_added: "1.0.0"
description:
    - Create, update, and delete Elasticsearch security users.
    - Requires the Elasticsearch Python client library.
options:
    name:
        description: Name of the Elasticsearch user.
        required: true
        type: str
    fullname:
        description: Full name of the user.
        required: false
        type: str
    password:
        description: Password for the user.
        required: true
        type: str
        no_log: true
    email:
        description: Email address of the user.
        required: false
        type: str
    roles:
        description: List of role names to assign to the user.
        required: true
        type: list
        elements: str
    enabled:
        description: Whether the user account is enabled.
        required: false
        type: bool
        default: true
    update_password:
        description:
            - When to update the user password.
            - C(always) will always send the password to Elasticsearch.
            - C(on_create) will only set the password when creating a new user.
        required: false
        type: str
        default: always
        choices: ['always', 'on_create']
    state:
        description: Whether the user should be present or absent.
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
- name: Create a user
  oddly.elasticstack.elasticsearch_user:
    name: my-user
    fullname: My User
    password: secret123
    email: user@example.com
    roles:
      - my-role
    enabled: true
    state: present
    host: https://localhost:9200
    auth_user: elastic
    auth_pass: changeme
    verify_certs: false

- name: Update user without changing password
  oddly.elasticstack.elasticsearch_user:
    name: my-user
    password: ignored
    roles:
      - new-role
    update_password: on_create
    host: https://localhost:9200
    auth_user: elastic
    auth_pass: changeme
    verify_certs: false

- name: Delete a user
  oddly.elasticstack.elasticsearch_user:
    name: my-user
    password: unused
    roles: []
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
    sample: "my-user has been created"
diff:
    description: Before and after state when running with --diff.
    returned: changed and diff mode
    type: dict
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.oddly.elasticstack.plugins.module_utils.elasticsearch_user import (
    User
)


def run_module():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            fullname=dict(type='str', required=False),
            password=dict(type='str', required=True, no_log=True),
            email=dict(type='str', required=False),
            roles=dict(type='list', required=True, elements='str'),
            enabled=dict(type='bool', required=False, default=True),
            update_password=dict(type='str', required=False, default='always',
                                 choices=['always', 'on_create']),
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

    user = User(
        module=module,
        user_name=module.params['name'],
        full_name=module.params['fullname'],
        password=module.params['password'],
        email=module.params['email'],
        roles=module.params['roles'],
        enabled=module.params['enabled'],
        state=module.params['state'],
        update_password=module.params['update_password'],
        host=module.params['host'],
        auth_user=module.params['auth_user'],
        auth_pass=module.params['auth_pass'],
        ca_certs=module.params['ca_certs'],
        verify_certs=module.params['verify_certs'],
    )

    result = user.return_result()
    module.exit_json(**result)


if __name__ == "__main__":
    run_module()
