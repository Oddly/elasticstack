#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (c) 2023, Daniel Patrick <daniel.patrick@netways.de>
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or
# https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r'''
---
module: cert_info
short_description: Retrieve information from a certificate file
description:
  - Reads a PKCS#12 or PEM certificate and returns metadata such as
    issuer, subject, validity dates, serial number, and supported X.509
    extensions.
options:
  path:
    description:
      - Path to the certificate file.
    type: str
    required: true
  passphrase:
    description:
      - Passphrase used to decrypt the certificate (required for PKCS#12).
    type: str
    required: false
    default: null
  format:
    description:
      - Format of the certificate file.
    type: str
    required: false
    default: p12
    choices: ['p12', 'pem']
author:
  - Daniel Patrick (@dpatrick-netways)
requirements:
  - cryptography >= 36.0
'''

EXAMPLES = r'''
- name: Get info from a PKCS#12 certificate
  oddly.elasticstack.cert_info:
    path: /etc/elasticsearch/certs/http.p12
    passphrase: changeme
  register: cert

- name: Get info from a PEM certificate
  oddly.elasticstack.cert_info:
    path: /etc/elasticsearch/certs/ca.pem
    format: pem
  register: cert
'''

RETURN = r'''
issuer:
  description: Common name of the certificate issuer.
  type: str
  returned: always
subject:
  description: Common name of the certificate subject.
  type: str
  returned: always
not_valid_after:
  description: Certificate expiry date.
  type: str
  returned: always
not_valid_before:
  description: Certificate start date.
  type: str
  returned: always
serial_number:
  description: Certificate serial number.
  type: str
  returned: always
version:
  description: Certificate version.
  type: str
  returned: always
extensions:
  description: Parsed X.509 extensions.
  type: dict
  returned: always
'''

from ansible.module_utils.basic import (
    AnsibleModule,
    to_native
)

from ansible_collections.oddly.elasticstack.plugins.module_utils.certs import (
    AnalyzeCertificate
)


def run_module():
    module_args = dict(
        path=dict(type='str', no_log=True, required=True),
        passphrase=dict(type='str', no_log=True, required=False, default=None),
        format=dict(type='str', required=False, default='p12', choices=['p12', 'pem'])
    )

    # seed the result dict
    result = dict(
        changed=False,
        extensions=dict(),
        issuer='',
        not_valid_after='',
        not_valid_before='',
        serial_number='',
        subject='',
        version=''
    )

    # the AnsibleModule object
    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True
    )

    # check mode
    if module.check_mode:
        module.exit_json(**result)

    try:
        cert_info = AnalyzeCertificate(module, result)
        result = cert_info.return_result()
    except ValueError as e:
        module.fail_json(msg='ValueError: %s' % to_native(e))
    except Exception as e:
        module.fail_json(msg='Exception: %s: %s' % (to_native(type(e)), to_native(e)))

    module.exit_json(**result)


def main():
    run_module()


if __name__ == '__main__':
    main()
