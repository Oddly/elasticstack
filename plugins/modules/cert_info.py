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
short_description: Read metadata from a PKCS#12 or PEM certificate
description:
  - Reads an X.509 certificate and returns its subject, issuer, validity dates,
    serial number, version, and selected extensions.
  - PKCS#12 files are used by default. Set C(format) to C(pem) for a PEM
    encoded certificate.
  - The private key and any additional certificates in a PKCS#12 bundle are
    used only to load the leaf certificate and are never returned.
author:
  - Daniel Patrick (@dpatrick)
  - Oddly contributors
options:
  path:
    description:
      - Absolute path to the certificate on the managed node.
    type: path
    required: true
  passphrase:
    description:
      - Passphrase for an encrypted PKCS#12 file.
      - PEM certificates do not require a passphrase.
    type: str
    required: false
    default: null
    no_log: true
  format:
    description:
      - Certificate encoding to read.
    type: str
    choices:
      - p12
      - pem
    default: p12
requirements:
  - cryptography >= 36.0 on the managed node
notes:
  - Only the supported extensions and extension values documented by this
    collection are returned.
'''

EXAMPLES = r'''
- name: Read an encrypted PKCS#12 CA certificate
  oddly.elasticstack.cert_info:
    path: /etc/elasticsearch/certs/elastic-stack-ca.p12
    passphrase: '{{ vault_elastic_ca_passphrase }}'
  register: elastic_ca_info

- name: Read a PEM certificate
  oddly.elasticstack.cert_info:
    path: /etc/elasticsearch/certs/ca.crt
    format: pem
'''

RETURN = r'''
issuer:
  description: Common name of the certificate issuer.
  returned: always
  type: str
subject:
  description: Common name of the certificate subject.
  returned: always
  type: str
not_valid_after:
  description: Certificate expiry timestamp.
  returned: always
  type: str
not_valid_before:
  description: Certificate validity start timestamp.
  returned: always
  type: str
serial_number:
  description: Certificate serial number.
  returned: always
  type: str
version:
  description: X.509 certificate version.
  returned: always
  type: str
extensions:
  description: Supported X.509 extensions and their values.
  returned: always
  type: dict
'''

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

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
