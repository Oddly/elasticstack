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


class User():
    def __init__(self, module, user_name, full_name, password, email,
                 roles, enabled, state, update_password,
                 host, auth_user, auth_pass, verify_certs, ca_certs):
        self.module = module
        self.user_name = user_name
        self.full_name = full_name
        self.password = password
        self.email = email
        self.roles = roles
        self.enabled = enabled
        self.state = state
        self.update_password = update_password
        self.result = dict(changed=False)

        try:
            self.client = Api.new_client_basic_auth(
                host=host, auth_user=auth_user, auth_pass=auth_pass,
                ca_certs=ca_certs, verify_certs=verify_certs
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
            all_users = self.get_all().raw
        except Exception as e:
            self.module.fail_json(
                msg="Failed to get users: %s" % str(e)
            )

        if self.user_name not in all_users:
            return

        if self.module.check_mode:
            self.result['changed'] = True
            self.result['msg'] = self.user_name + " would be deleted"
            return

        try:
            res = self.delete()
        except Exception as e:
            self.module.fail_json(
                msg="Failed to delete user '%s': %s" % (self.user_name, str(e))
            )

        if res['found'] is True:
            self.result['changed'] = True
            self.result['msg'] = self.user_name + " has been deleted"

    def handle_present(self):
        try:
            all_users = self.get_all().raw
        except Exception as e:
            self.module.fail_json(
                msg="Failed to get users: %s" % str(e)
            )

        user_exists = self.user_name in all_users
        if user_exists:
            pre_user = self.get()
        else:
            pre_user = None

        if self.module.check_mode:
            self.result['changed'] = True
            if pre_user is None:
                self.result['msg'] = self.user_name + " would be created"
            else:
                self.result['msg'] = self.user_name + " would be updated"
            return

        try:
            # When update_password is 'on_create' and user exists, skip password
            send_password = self.password
            if self.update_password == 'on_create' and user_exists:
                send_password = None

            res = self.put(password=send_password)
        except Exception as e:
            self.module.fail_json(
                msg="Failed to create/update user '%s': %s" % (self.user_name, str(e))
            )

        if res.raw['created'] is True:
            self.result['changed'] = True
            self.result['msg'] = self.user_name + " has been created"
            if self.module._diff:
                self.result['diff'] = dict(before='', after=str(self.get().raw))
            return

        if pre_user is None:
            return

        # Compare user properties excluding password hash (which always changes)
        post_user = self.get()
        pre_data = pre_user.raw.get(self.user_name, {})
        post_data = post_user.raw.get(self.user_name, {})
        compare_keys = ('roles', 'full_name', 'email', 'enabled', 'metadata')
        pre_compare = {k: pre_data.get(k) for k in compare_keys}
        post_compare = {k: post_data.get(k) for k in compare_keys}

        if pre_compare != post_compare:
            self.result['changed'] = True
            self.result['msg'] = self.user_name + " has been updated"
            if self.module._diff:
                self.result['diff'] = dict(
                    before=str(pre_data),
                    after=str(post_data)
                )

    def get_all(self):
        return self.client.security.get_user()

    def get(self):
        return self.client.security.get_user(username=self.user_name)

    def put(self, password=None):
        kwargs = dict(
            username=self.user_name,
            email=self.email,
            full_name=self.full_name,
            enabled=self.enabled,
            roles=self.roles,
        )
        if password is not None:
            kwargs['password'] = password
        return self.client.security.put_user(**kwargs)

    def delete(self):
        return self.client.security.delete_user(username=self.user_name)
