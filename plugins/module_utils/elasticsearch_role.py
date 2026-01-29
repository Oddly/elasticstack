#!/usr/bin/python

# Copyright (c) 2024, Tobias Bauriedel <tobias.bauriedel@netways.de>
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or
# https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible_collections.oddly.elasticstack.plugins.module_utils.api import (
    Api,
    ApiError
)


class Role():
    def __init__(self, module, role_name, cluster, indices, state,
                 host, auth_user, auth_pass, verify_certs, ca_certs):
        self.module = module
        self.role_name = role_name
        self.cluster = cluster
        self.indices = indices
        self.state = state
        self.result = dict(changed=False)

        try:
            self.client = Api.new_client_basic_auth(
                host=host, auth_user=auth_user, auth_pass=auth_pass,
                verify_certs=verify_certs, ca_certs=ca_certs
            )
        except ApiError as e:
            self.module.fail_json(msg=str(e))

        self.handle()

    def return_result(self):
        return self.result

    def handle(self):
        if self.state == 'absent':
            self.handle_absent()
        elif self.state == 'present':
            self.handle_present()

    def handle_absent(self):
        try:
            all_roles = self.get_all().raw
        except Exception as e:
            self.module.fail_json(
                msg="Failed to get roles: %s" % str(e)
            )

        if self.role_name not in all_roles:
            return

        if self.module.check_mode:
            self.result['changed'] = True
            self.result['msg'] = self.role_name + " would be deleted"
            return

        try:
            res = self.delete()
        except Exception as e:
            self.module.fail_json(
                msg="Failed to delete role '%s': %s" % (self.role_name, str(e))
            )

        if res['found'] is True:
            self.result['changed'] = True
            self.result['msg'] = self.role_name + " has been deleted"

    def handle_present(self):
        try:
            all_roles = self.get_all().raw
        except Exception as e:
            self.module.fail_json(
                msg="Failed to get roles: %s" % str(e)
            )

        if self.role_name in all_roles:
            pre_role = self.get()
        else:
            pre_role = None

        if self.module.check_mode:
            self.result['changed'] = True
            if pre_role is None:
                self.result['msg'] = self.role_name + " would be created"
            else:
                self.result['msg'] = self.role_name + " would be updated"
            return

        try:
            res = self.put()
        except Exception as e:
            self.module.fail_json(
                msg="Failed to create/update role '%s': %s" % (self.role_name, str(e))
            )

        if res.raw['role']['created'] is True:
            self.result['changed'] = True
            self.result['msg'] = self.role_name + " has been created"
            if self.module._diff:
                self.result['diff'] = dict(before='', after=str(self.get().raw))
            return

        if pre_role is None:
            return

        post_role = self.get()
        if pre_role.raw != post_role.raw:
            self.result['changed'] = True
            self.result['msg'] = self.role_name + " has been updated"
            if self.module._diff:
                self.result['diff'] = dict(
                    before=str(pre_role.raw),
                    after=str(post_role.raw)
                )

    def get_all(self):
        return self.client.security.get_role()

    def get(self):
        return self.client.security.get_role(name=self.role_name)

    def put(self):
        return self.client.security.put_role(
            name=self.role_name, cluster=self.cluster, indices=self.indices
        )

    def delete(self):
        return self.client.security.delete_role(name=self.role_name)
