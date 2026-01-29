# -*- coding: utf-8 -*-

# Copyright (c) 2023, Daniel Patrick <daniel.patrick@netways.de>
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or
# https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function
__metaclass__ = type

from ansible.module_utils.basic import (
    missing_required_lib,
    to_text,
    to_native,
    to_bytes
)

try:
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
    HAS_CRYPTOGRAPHY_PKCS12 = True
except ImportError:
    HAS_CRYPTOGRAPHY_PKCS12 = False

SUPPORTED_EXTENSIONS = {
    'basicConstraints': [
        '_ca',
        '_path_length'
    ],
    'subjectKeyIdentifier': [
        '_digest'
    ],
    'authorityKeyIdentifier': [
        '_authority_cert_issuer',
        '_authority_cert_serial_number',
        '_key_identifier'
    ]
}


def bytes_to_hex(bytes_str):
    """Convert bytes to a colon-separated hex string (e.g. 'AB:CD:EF')."""
    return ':'.join('%02X' % b for b in bytes_str)


def check_supported_extensions(extension_name):
    """Return True if extension_name matches a supported extension."""
    return any(name in extension_name for name in SUPPORTED_EXTENSIONS)


def check_supported_keys(key, extension_name):
    """Return True if key is a supported key for the given extension."""
    return key in SUPPORTED_EXTENSIONS.get(extension_name, [])


class AnalyzeCertificate():
    def __init__(self, module, result):
        self.module = module
        self.result = result
        self.__passphrase = self.module.params['passphrase']
        self.__path = self.module.params['path']
        self.__cert = None
        self.__private_key = None
        self.__additional_certs = None
        self.load_certificate()
        self.load_info()

    def load_certificate(self):
        if not HAS_CRYPTOGRAPHY_PKCS12:
            self.module.fail_json(
                msg=missing_required_lib('cryptography >= 36.0')
            )

        try:
            with open(self.__path, 'rb') as f:
                pkcs12_data = f.read()
        except IOError as e:
            self.module.fail_json(
                msg='IOError: %s' % (to_native(e))
            )

        try:
            pkcs12_tuple = pkcs12.load_key_and_certificates(
                pkcs12_data,
                to_bytes(self.__passphrase),
            )
        except ValueError as e:
            self.module.fail_json(
                msg='Failed to load PKCS12 certificate: %s' % (to_native(e))
            )

        self.__private_key = pkcs12_tuple[0]
        self.__cert = pkcs12_tuple[1]
        self.__additional_certs = pkcs12_tuple[2]

    def load_info(self):
        self.general_info()
        self.extensions_info()

    def general_info(self):
        issuer_attrs = self.__cert.issuer.get_attributes_for_oid(
            NameOID.COMMON_NAME
        )
        subject_attrs = self.__cert.subject.get_attributes_for_oid(
            NameOID.COMMON_NAME
        )

        self.result['issuer'] = to_text(issuer_attrs[0].value) if issuer_attrs else ''
        self.result['subject'] = to_text(subject_attrs[0].value) if subject_attrs else ''
        # Use not_valid_after_utc to avoid deprecation warning (cryptography >= 42.0)
        if hasattr(self.__cert, 'not_valid_after_utc'):
            self.result['not_valid_after'] = to_text(self.__cert.not_valid_after_utc)
            self.result['not_valid_before'] = to_text(self.__cert.not_valid_before_utc)
        else:
            self.result['not_valid_after'] = to_text(self.__cert.not_valid_after)
            self.result['not_valid_before'] = to_text(self.__cert.not_valid_before)
        self.result['serial_number'] = to_text(self.__cert.serial_number)
        self.result['version'] = to_text(self.__cert.version)

    def extensions_info(self):
        for extension in self.__cert.extensions:
            name = to_text(extension.oid._name)
            if not check_supported_extensions(name):
                continue
            try:
                self.result['extensions'][name] = dict()
                self.result['extensions'][name]['_dotted_string'] = to_text(
                    extension.oid.dotted_string
                )
                self.result['extensions'][name]['_critical'] = to_text(
                    extension.critical
                )
                self._load_extension_values(name, extension)
            except Exception as e:
                self.module.warn(
                    "Failed to parse extension '%s': %s" % (name, to_native(e))
                )

    def _load_extension_values(self, name, extension):
        self.result['extensions'][name]['_values'] = dict()
        for key, value in vars(extension.value).items():
            if not check_supported_keys(key, name):
                continue
            if isinstance(value, bytes):
                value = bytes_to_hex(value)
            self.result['extensions'][name]['_values'][to_text(key)] = to_text(value)

    def return_result(self):
        return self.result
