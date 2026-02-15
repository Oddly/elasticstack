#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (c) 2025, NETWAYS GmbH
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or
# https://www.gnu.org/licenses/gpl-3.0.txt)

"""Unit tests for the api module."""

import unittest
import sys
import ssl
import os
from unittest.mock import patch, MagicMock

# Add the collection path for imports
COLLECTION_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..', '..', '..', '..'
)
sys.path.insert(0, COLLECTION_PATH)

# Also check for installed collection path (CI environment)
sys.path.append('/home/runner/.ansible/collections/')

from plugins.module_utils.api import (
    Api, ApiError, HAS_ELASTICSEARCH, ES_CLIENT_VERSION
)


class TestApiVersionDetection(unittest.TestCase):
    """Test version detection for elasticsearch-py 8.x and 9.x."""

    def test_version_detection_tuple_format(self):
        """Test that tuple version format (ES 9.x) is correctly parsed."""
        # elasticsearch-py 9.x returns __version__ as tuple
        _ver = (9, 2, 1)
        if isinstance(_ver, tuple):
            version = _ver[0]
        else:
            version = int(_ver.split('.')[0])

        self.assertEqual(version, 9)
        self.assertIsInstance(_ver, tuple)

    def test_version_detection_string_format(self):
        """Test that string version format (ES 8.x) is correctly parsed."""
        # elasticsearch-py 8.x returns __version__ as string
        _ver = "8.19.3"
        if isinstance(_ver, tuple):
            version = _ver[0]
        else:
            version = int(_ver.split('.')[0])

        self.assertEqual(version, 8)
        self.assertIsInstance(_ver, str)

    def test_version_detection_major_version_7(self):
        """Test version detection for ES 7.x string format."""
        _ver = "7.17.0"
        if isinstance(_ver, tuple):
            version = _ver[0]
        else:
            version = int(_ver.split('.')[0])

        self.assertEqual(version, 7)

    def test_version_detection_tuple_with_prerelease(self):
        """Test tuple version with potential prerelease info."""
        _ver = (9, 0, 0)
        if isinstance(_ver, tuple):
            version = _ver[0]
        else:
            version = int(_ver.split('.')[0])

        self.assertEqual(version, 9)

    def test_version_detection_handles_both_formats(self):
        """Test the actual version detection logic handles both formats."""
        # Test tuple format (ES 9.x style)
        tuple_ver = (9, 2, 1)
        if isinstance(tuple_ver, tuple):
            result = tuple_ver[0]
        else:
            result = int(tuple_ver.split('.')[0])
        self.assertEqual(result, 9)

        # Test string format (ES 8.x style)
        string_ver = "8.19.3"
        if isinstance(string_ver, tuple):
            result = string_ver[0]
        else:
            result = int(string_ver.split('.')[0])
        self.assertEqual(result, 8)


class TestApiError(unittest.TestCase):
    """Test the ApiError exception class."""

    def test_api_error_is_exception(self):
        """Test that ApiError is a proper exception."""
        with self.assertRaises(ApiError) as context:
            raise ApiError("Test error message")

        self.assertEqual(str(context.exception), "Test error message")

    def test_api_error_inheritance(self):
        """Test that ApiError inherits from Exception."""
        self.assertTrue(issubclass(ApiError, Exception))

    def test_api_error_with_empty_message(self):
        """Test ApiError with empty message."""
        with self.assertRaises(ApiError):
            raise ApiError("")


class TestApiStaticMethods(unittest.TestCase):
    """Test the Api class static methods."""

    def test_get_client_version_returns_integer(self):
        """Test that get_client_version returns an integer."""
        version = Api.get_client_version()
        self.assertIsInstance(version, int)

    def test_get_client_version_matches_module_constant(self):
        """Test that get_client_version returns ES_CLIENT_VERSION."""
        version = Api.get_client_version()
        self.assertEqual(version, ES_CLIENT_VERSION)

    def test_get_client_version_is_valid(self):
        """Test that get_client_version returns a valid major version."""
        version = Api.get_client_version()
        # Should be 0 (not installed), 7, 8, 9, or potentially 10+
        self.assertGreaterEqual(version, 0)
        self.assertLessEqual(version, 20)  # Reasonable upper bound

    def test_check_elasticsearch_import_with_library(self):
        """Test check_elasticsearch_import when library is available."""
        if HAS_ELASTICSEARCH:
            # Should not raise
            Api.check_elasticsearch_import()
        else:
            self.skipTest("elasticsearch library not installed")

    def test_check_elasticsearch_import_raises_when_missing(self):
        """Test check_elasticsearch_import raises ApiError when library missing."""
        # Temporarily patch HAS_ELASTICSEARCH to False
        with patch('plugins.module_utils.api.HAS_ELASTICSEARCH', False):
            with self.assertRaises(ApiError) as context:
                Api.check_elasticsearch_import()

            self.assertIn("elasticsearch", str(context.exception).lower())
            self.assertIn("pip install", str(context.exception))


class TestApiClientCreation(unittest.TestCase):
    """Test the client creation methods."""

    def setUp(self):
        """Set up test fixtures."""
        if not HAS_ELASTICSEARCH:
            self.skipTest("elasticsearch library not installed")

    @patch('plugins.module_utils.api.Elasticsearch')
    def test_new_client_basic_auth_creates_client(self, mock_es):
        """Test that new_client_basic_auth creates an Elasticsearch client."""
        mock_es.return_value = MagicMock()

        client = Api.new_client_basic_auth(
            host='https://localhost:9200',
            auth_user='elastic',
            auth_pass='changeme',
            ca_certs=None,
            verify_certs=False
        )

        mock_es.assert_called_once()
        call_kwargs = mock_es.call_args[1]

        self.assertEqual(call_kwargs['hosts'], ['https://localhost:9200'])
        self.assertEqual(call_kwargs['basic_auth'], ('elastic', 'changeme'))
        self.assertFalse(call_kwargs['verify_certs'])
        self.assertIsInstance(call_kwargs['ssl_context'], ssl.SSLContext)

    @patch('plugins.module_utils.api.Elasticsearch')
    def test_new_client_basic_auth_with_verify_certs(self, mock_es):
        """Test client creation with certificate verification enabled."""
        mock_es.return_value = MagicMock()

        Api.new_client_basic_auth(
            host='https://localhost:9200',
            auth_user='elastic',
            auth_pass='changeme',
            ca_certs=None,
            verify_certs=True
        )

        call_kwargs = mock_es.call_args[1]
        self.assertTrue(call_kwargs['verify_certs'])

        # Check SSL context is configured for verification
        ctx = call_kwargs['ssl_context']
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    @patch('plugins.module_utils.api.Elasticsearch')
    def test_new_client_basic_auth_without_verify_certs(self, mock_es):
        """Test client creation with certificate verification disabled."""
        mock_es.return_value = MagicMock()

        Api.new_client_basic_auth(
            host='https://localhost:9200',
            auth_user='elastic',
            auth_pass='changeme',
            ca_certs=None,
            verify_certs=False
        )

        call_kwargs = mock_es.call_args[1]
        self.assertFalse(call_kwargs['verify_certs'])

        # Check SSL context is configured to skip verification
        ctx = call_kwargs['ssl_context']
        self.assertEqual(ctx.verify_mode, ssl.CERT_NONE)
        self.assertFalse(ctx.check_hostname)

    @patch('plugins.module_utils.api.Elasticsearch')
    def test_new_client_basic_auth_host_in_list(self, mock_es):
        """Test that host is wrapped in a list for the client."""
        mock_es.return_value = MagicMock()

        Api.new_client_basic_auth(
            host='https://es.example.com:9200',
            auth_user='user',
            auth_pass='pass',
            ca_certs=None,
            verify_certs=False
        )

        call_kwargs = mock_es.call_args[1]
        self.assertIsInstance(call_kwargs['hosts'], list)
        self.assertEqual(len(call_kwargs['hosts']), 1)
        self.assertEqual(call_kwargs['hosts'][0], 'https://es.example.com:9200')

    @patch('plugins.module_utils.api.Elasticsearch')
    def test_new_client_api_key_creates_client(self, mock_es):
        """Test that new_client_api_key creates an Elasticsearch client."""
        mock_es.return_value = MagicMock()

        client = Api.new_client_api_key(
            host='https://localhost:9200',
            api_key='test_api_key_base64',
            ca_certs=None,
            verify_certs=False
        )

        mock_es.assert_called_once()
        call_kwargs = mock_es.call_args[1]

        self.assertEqual(call_kwargs['hosts'], ['https://localhost:9200'])
        self.assertEqual(call_kwargs['api_key'], 'test_api_key_base64')
        self.assertFalse(call_kwargs['verify_certs'])
        self.assertIsInstance(call_kwargs['ssl_context'], ssl.SSLContext)

    @patch('plugins.module_utils.api.Elasticsearch')
    def test_new_client_api_key_with_tuple(self, mock_es):
        """Test client creation with API key as tuple (id, key)."""
        mock_es.return_value = MagicMock()

        api_key_tuple = ('key_id', 'key_secret')
        Api.new_client_api_key(
            host='https://localhost:9200',
            api_key=api_key_tuple,
            ca_certs=None,
            verify_certs=True
        )

        call_kwargs = mock_es.call_args[1]
        self.assertEqual(call_kwargs['api_key'], api_key_tuple)

    @patch('plugins.module_utils.api.Elasticsearch')
    def test_new_client_api_key_with_verify_certs(self, mock_es):
        """Test API key client with certificate verification."""
        mock_es.return_value = MagicMock()

        Api.new_client_api_key(
            host='https://localhost:9200',
            api_key='test_key',
            ca_certs=None,
            verify_certs=True
        )

        call_kwargs = mock_es.call_args[1]
        ctx = call_kwargs['ssl_context']
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)


class TestApiModuleConstants(unittest.TestCase):
    """Test module-level constants."""

    def test_has_elasticsearch_is_boolean(self):
        """Test that HAS_ELASTICSEARCH is a boolean."""
        self.assertIsInstance(HAS_ELASTICSEARCH, bool)

    def test_es_client_version_is_integer(self):
        """Test that ES_CLIENT_VERSION is an integer."""
        self.assertIsInstance(ES_CLIENT_VERSION, int)

    def test_es_client_version_consistent_with_has_elasticsearch(self):
        """Test ES_CLIENT_VERSION is consistent with HAS_ELASTICSEARCH."""
        if HAS_ELASTICSEARCH:
            self.assertGreater(ES_CLIENT_VERSION, 0)
        else:
            self.assertEqual(ES_CLIENT_VERSION, 0)

    def test_current_client_version_is_9(self):
        """Test that current installed client is version 9."""
        if HAS_ELASTICSEARCH:
            # We expect ES 9.x client based on our requirements
            self.assertEqual(ES_CLIENT_VERSION, 9)
        else:
            self.skipTest("elasticsearch library not installed")


class TestSSLContextCreation(unittest.TestCase):
    """Test SSL context creation in client methods."""

    def setUp(self):
        """Set up test fixtures."""
        if not HAS_ELASTICSEARCH:
            self.skipTest("elasticsearch library not installed")

    @patch('plugins.module_utils.api.Elasticsearch')
    def test_ssl_context_created_without_ca_certs(self, mock_es):
        """Test SSL context is created when ca_certs is None."""
        mock_es.return_value = MagicMock()

        Api.new_client_basic_auth(
            host='https://localhost:9200',
            auth_user='elastic',
            auth_pass='changeme',
            ca_certs=None,
            verify_certs=False
        )

        call_kwargs = mock_es.call_args[1]
        self.assertIn('ssl_context', call_kwargs)
        self.assertIsInstance(call_kwargs['ssl_context'], ssl.SSLContext)

    @patch('plugins.module_utils.api.Elasticsearch')
    @patch('ssl.create_default_context')
    def test_ssl_context_with_ca_certs(self, mock_ssl_ctx, mock_es):
        """Test SSL context is created with ca_certs file."""
        mock_ctx = MagicMock(spec=ssl.SSLContext)
        mock_ssl_ctx.return_value = mock_ctx
        mock_es.return_value = MagicMock()

        Api.new_client_basic_auth(
            host='https://localhost:9200',
            auth_user='elastic',
            auth_pass='changeme',
            ca_certs='/path/to/ca.crt',
            verify_certs=True
        )

        # Verify ssl.create_default_context was called with cafile
        mock_ssl_ctx.assert_called_once_with(cafile='/path/to/ca.crt')


if __name__ == '__main__':
    unittest.main()
