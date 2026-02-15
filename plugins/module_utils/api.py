# !/usr/bin/python3

# Copyright (c) 2024, Tobias Bauriedel <tobias.bauriedel@netways.de>
# Copyright (c) 2025, NETWAYS GmbH
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or
# https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import ssl

def parse_version(version):
    """
    Parse version to extract major version number.

    Handles both formats:
    - tuple: (9, 0, 0) from elasticsearch-py 9.x
    - string: "8.19.3" from elasticsearch-py 8.x or ES server API

    Args:
        version: Version as tuple or string

    Returns:
        int: Major version number
    """
    if isinstance(version, tuple):
        return version[0]
    return int(str(version).split('.')[0])


try:
    from elasticsearch import Elasticsearch
    import elasticsearch
    HAS_ELASTICSEARCH = True
    # Detect client version for compatibility
    # elasticsearch-py 9.x: __version__ is tuple (9, 0, 0)
    # elasticsearch-py 8.x: __version__ is string "8.19.3"
    ES_CLIENT_VERSION = parse_version(elasticsearch.__version__)
except ImportError:
    HAS_ELASTICSEARCH = False
    ES_CLIENT_VERSION = 0


class ApiError(Exception):
    """Custom exception for API errors."""
    pass


class ApiCompatibilityWarning(UserWarning):
    """Warning for client/server version compatibility issues."""
    pass


class Api():
    """
    Elasticsearch API client wrapper.

    Provides a unified interface for creating Elasticsearch clients
    that works with both elasticsearch-py 8.x and 9.x versions.

    The elasticsearch-py 9.x client has several breaking changes:
    - timeout -> request_timeout
    - randomize_hosts -> randomize_nodes_in_pool
    - sniffer_timeout -> min_delay_between_sniffing
    - sniff_on_connection_fail -> sniff_on_node_failure
    - maxsize -> connections_per_node
    - url_prefix -> path_prefix
    - use_ssl removed (scheme inferred from URL)

    This class handles these differences transparently.
    """

    @staticmethod
    def check_elasticsearch_import():
        """Check if elasticsearch library is available."""
        if not HAS_ELASTICSEARCH:
            raise ApiError(
                "The 'elasticsearch' Python library is required. "
                "Install it with: pip install 'elasticsearch>=8,<9' (for ES 8.x) "
                "or 'elasticsearch>=9,<10' (for ES 9.x)"
            )

    @staticmethod
    def get_client_version():
        """Return the major version of the elasticsearch-py client."""
        return ES_CLIENT_VERSION

    @staticmethod
    def get_server_version(client):
        """
        Get the major version of the Elasticsearch server.

        Args:
            client: Elasticsearch client instance

        Returns:
            int: Major version number of the server
        """
        info = client.info()
        return parse_version(info['version']['number'])

    @staticmethod
    def check_version_compatibility(client):
        """
        Check compatibility between elasticsearch-py client and ES server.

        The elasticsearch-py client follows these compatibility rules:
        - Forward compatible: 8.x client works with 8.x and 9.x servers
        - NOT backward compatible: 9.x client does NOT work with 8.x servers

        Args:
            client: Elasticsearch client instance

        Returns:
            dict: Compatibility info with keys:
                - compatible (bool): Whether versions are compatible
                - client_version (int): Client major version
                - server_version (int): Server major version
                - message (str): Human-readable compatibility message

        Raises:
            ApiError: If client 9.x is used with server 8.x (incompatible)
        """
        client_ver = Api.get_client_version()
        server_ver = Api.get_server_version(client)

        result = {
            'client_version': client_ver,
            'server_version': server_ver,
            'compatible': True,
            'message': ''
        }

        if client_ver == 9 and server_ver == 8:
            # This combination will fail - elasticsearch-py 9.x is not backward compatible
            result['compatible'] = False
            result['message'] = (
                f"Incompatible versions: elasticsearch-py {client_ver}.x cannot connect to "
                f"Elasticsearch {server_ver}.x. Install 'elasticsearch>=8,<9' or upgrade "
                "your Elasticsearch server to 9.x first."
            )
            raise ApiError(result['message'])

        elif client_ver == 8 and server_ver == 9:
            # This works but user might want to upgrade for new features
            result['message'] = (
                f"elasticsearch-py {client_ver}.x is forward-compatible with Elasticsearch "
                f"{server_ver}.x. Consider upgrading to 'elasticsearch>=9,<10' for full "
                "ES 9.x feature support."
            )

        elif client_ver == server_ver:
            result['message'] = (
                f"elasticsearch-py {client_ver}.x is fully compatible with "
                f"Elasticsearch {server_ver}.x."
            )

        else:
            result['message'] = (
                f"elasticsearch-py {client_ver}.x with Elasticsearch {server_ver}.x - "
                "compatibility not verified."
            )

        return result

    @staticmethod
    def _create_ssl_context(ca_certs, verify_certs):
        """
        Create an SSL context for Elasticsearch connections.

        Args:
            ca_certs: Path to CA certificate file (optional)
            verify_certs: Whether to verify SSL certificates

        Returns:
            ssl.SSLContext: Configured SSL context
        """
        if ca_certs:
            ctx = ssl.create_default_context(cafile=ca_certs)
        else:
            ctx = ssl.create_default_context()

        if not verify_certs:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        else:
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED

        return ctx

    @staticmethod
    def new_client_basic_auth(host, auth_user, auth_pass, ca_certs, verify_certs) -> 'Elasticsearch':
        """
        Create an Elasticsearch client using basic authentication.

        This method is compatible with both elasticsearch-py 8.x and 9.x.

        Args:
            host: Elasticsearch host URL (e.g., 'https://localhost:9200')
            auth_user: Username for authentication
            auth_pass: Password for authentication
            ca_certs: Path to CA certificate file (optional)
            verify_certs: Whether to verify SSL certificates

        Returns:
            Elasticsearch client instance

        Raises:
            ApiError: If elasticsearch library is not installed
        """
        Api.check_elasticsearch_import()

        return Elasticsearch(
            hosts=[host],
            basic_auth=(auth_user, auth_pass),
            ssl_context=Api._create_ssl_context(ca_certs, verify_certs),
            verify_certs=verify_certs,
        )

    @staticmethod
    def new_client_api_key(host, api_key, ca_certs, verify_certs) -> 'Elasticsearch':
        """
        Create an Elasticsearch client using API key authentication.

        This method is compatible with both elasticsearch-py 8.x and 9.x.

        Args:
            host: Elasticsearch host URL (e.g., 'https://localhost:9200')
            api_key: API key for authentication (base64 encoded or tuple of (id, key))
            ca_certs: Path to CA certificate file (optional)
            verify_certs: Whether to verify SSL certificates

        Returns:
            Elasticsearch client instance

        Raises:
            ApiError: If elasticsearch library is not installed
        """
        Api.check_elasticsearch_import()

        return Elasticsearch(
            hosts=[host],
            api_key=api_key,
            ssl_context=Api._create_ssl_context(ca_certs, verify_certs),
            verify_certs=verify_certs,
        )
