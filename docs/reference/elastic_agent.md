# elastic_agent

Ansible role for installing and managing Elastic Agent on Linux. It supports a complete standalone `elastic-agent.yml` policy, Fleet enrollment using a policy token, and a self-managed Fleet Server using the `servers` package flavor. The role covers Elastic Stack 8.x and 9.x and uses the shared repository and package-installation tasks.

Elastic documents standalone mode as a locally managed policy with a default output and at least one input. Fleet mode is centrally managed by Kibana. The role follows those boundaries: it deploys the local policy or executes enrollment, but it does not invent Fleet policies or tokens. See [Elastic Agent installation](https://www.elastic.co/docs/reference/fleet/install-standalone-elastic-agent), [standalone configuration](https://www.elastic.co/docs/reference/fleet/configure-standalone-elastic-agents), and the [command reference](https://www.elastic.co/docs/reference/fleet/agent-command-reference).

## Lifecycle

```yaml
elastic_agent_manage: false
elastic_agent_enable: true
elastic_agent_mode: standalone
elastic_agent_package_flavor: basic
elastic_agent_config_backup: false
elastic_agent_migrate_from_beats: false
```

`elastic_agent_manage` defaults to `false` so an accidentally included role cannot install an agent without a policy or enrollment credentials. Set it to `true` on the intended hosts. `elastic_agent_enable` controls the systemd service. `elastic_agent_mode` accepts `standalone`, `fleet`, or `fleet_server`. On 9.x, `elastic_agent_package_flavor` accepts `basic` or `servers`, and Fleet Server mode requires `servers`; on 8.x use `basic` because the regular package includes Fleet Server. `elastic_agent_config_backup` controls backups of the standalone policy. `elastic_agent_migrate_from_beats` configures and enrolls the Agent before stopping and disabling the three Beat services, leaving their packages and configuration available for rollback. If the later Agent lifecycle fails, the role restores their previous service state.

The package layout variables are useful for package wrappers or a non-default package layout:

```yaml
elastic_agent_binary_path: /usr/bin/elastic-agent
elastic_agent_config_dir: /etc/elastic-agent
elastic_agent_config_file: "{{ elastic_agent_config_dir }}/elastic-agent.yml"
elastic_agent_package_flavor_file: ""
elastic_agent_certificate_dir: "{{ elastic_agent_config_dir }}/certs"
elastic_agent_enrollment_state_file: "{{ elastic_agent_config_dir }}/.enrollment.sha256"
```

The default paths match the DEB and RPM installation layout. The role creates
the parent directory of `elastic_agent_config_file`, including when it is
outside `elastic_agent_config_dir`; configure the installed service to read a
custom path when needed. On 9.x, the package flavor marker is configured with
`elastic_agent_package_flavor_file`. Its empty default resolves the marker at
the active package's top directory. The active package binary is stored under
the versioned `/var/lib/elastic-agent/data` directory, so the default marker is
`/var/lib/elastic-agent/.flavor`; set an explicit path for a custom package
layout. 8.x packages do not use a flavor marker.
The enrollment state file contains only a SHA-256 fingerprint and can be moved
to a separate persistent path when the configuration directory is ephemeral.

## Standalone policy

```yaml
elasticstack_full_stack: false
elastic_agent_standalone_config:
  outputs:
    default:
      type: elasticsearch
      hosts:
        - https://es.example.test:9200
      api_key: "{{ vault_agent_api_key }}"
  inputs:
    - type: system/metrics
      id: system-metrics
      data_stream.namespace: default
      streams:
        - metricsets:
            - cpu
            - memory
          data_stream.dataset: system
```

`elastic_agent_standalone_config` is rendered as YAML with mode `0600`. It is treated as sensitive because a standalone policy commonly contains an API key, username/password, or client credentials. The role validates that the dictionary is non-empty; Elastic Agent validates the policy's output and input details when the service starts.

## Fleet enrollment

```yaml
elastic_agent_fleet_server_url: https://fleet.example.test:8220
elastic_agent_enrollment_token: "{{ vault_fleet_enrollment_token }}"
elastic_agent_fleet_server_insecure: false
elastic_agent_fleet_server_ca_source: none
elastic_agent_fleet_server_ca_file: ""
elastic_agent_fleet_server_ca_content: ""
elastic_agent_fleet_server_ca_remote_src: false
```

Use `elastic_agent_mode: fleet` with the URL and enrollment token generated for the agent policy. `elastic_agent_fleet_server_insecure` adds `--insecure` and should be limited to temporary development use. For a public CA, leave `elastic_agent_fleet_server_ca_source` at `none`. For the collection CA, use `elasticsearch_ca`; for a private CA, use `external` and set either `elastic_agent_fleet_server_ca_file` or `elastic_agent_fleet_server_ca_content`. Set `elastic_agent_fleet_server_ca_remote_src` when the file already exists on the managed host.

Enrollment uses the package's `elastic-agent enroll` command with an argv list, so URLs and tokens are not assembled into a shell command. The role hashes the desired command inputs into `elastic_agent_enrollment_state_file` internally and also checks the package-managed encrypted Fleet state at `{{ elastic_agent_config_dir }}/fleet.enc`. A matching marker skips enrollment only when that Fleet state exists. If the state is recreated, enrollment runs again; if an existing Fleet state has no matching marker, the role refuses to run `--force` because that can create duplicate Fleet agents. The marker contains no token or policy content.

## Fleet Server

```yaml
elastic_agent_fleet_server_es: ""
elastic_agent_fleet_server_service_token: "{{ vault_fleet_service_token }}"
elastic_agent_fleet_server_service_token_file: "{{ elastic_agent_config_dir }}/.fleet-server-service-token"
elastic_agent_fleet_server_policy: fleet-server-policy-id
elastic_agent_fleet_server_host: ""
elastic_agent_fleet_server_port: 8220
```

Use `elastic_agent_mode: fleet_server` and set `elastic_agent_package_flavor: servers` on 9.x. On 8.x, use `basic` because the regular package includes Fleet Server. `elastic_agent_fleet_server_es` is the Elasticsearch URL; when empty, the role derives it from the first host in `elasticstack_elasticsearch_group_name`, preferring `elasticsearch_http_publish_host` and `elasticsearch_http_publish_port` and falling back to the inventory address and shared HTTP port. `elastic_agent_fleet_server_service_token` is the Elasticsearch service token, while `elastic_agent_fleet_server_policy` is the Fleet Server policy ID. The service token is stored in the root-owned `0600` file at `elastic_agent_fleet_server_service_token_file` and passed with `--fleet-server-service-token-path`. An `http://` Elasticsearch URL also adds `--fleet-server-es-insecure`; TLS is preferred. The enrollment token remains a command argument because Elastic Agent does not provide an enrollment-token path option, so use a short-lived token and protect access to the host process table during enrollment. `elastic_agent_fleet_server_host` and `elastic_agent_fleet_server_port` add the corresponding Fleet Server command options.

The Fleet Server TLS inputs are:

```yaml
elastic_agent_fleet_server_cert_file: ""
elastic_agent_fleet_server_cert_content: ""
elastic_agent_fleet_server_cert_key_file: ""
elastic_agent_fleet_server_cert_key_content: ""
elastic_agent_fleet_server_cert_remote_src: false
elastic_agent_fleet_server_es_ca_file: ""
elastic_agent_fleet_server_es_ca_content: ""
elastic_agent_fleet_server_es_ca_remote_src: false
```

The certificate and private key are copied to `elastic_agent_certificate_dir`
(default `/etc/elastic-agent/certs/`) and passed to the Fleet Server enrollment
command. The Elasticsearch CA is copied separately and passed with
`--fleet-server-es-ca`. For each file/content pair, content takes precedence;
`elastic_agent_fleet_server_cert_remote_src` and
`elastic_agent_fleet_server_es_ca_remote_src` apply to file inputs. The CA
selected through `elastic_agent_fleet_server_ca_source` is passed as
`--certificate-authorities` for the Fleet Server endpoint.

## Migration and upgrades

The package version follows the shared `elasticstack_version` setting, so setting an exact version upgrades the DEB or RPM through the package manager and restarts the service when needed. Package-based Fleet Agents do not support Fleet-managed binary upgrades; use the collection's package version controls for those upgrades. Set `elastic_agent_migrate_from_beats: true` for a controlled handover from the individual Beat services. The role completes Agent configuration and enrollment before disabling Beats and restores their previous service state if the later Agent lifecycle fails. Then move the existing Beat policy into Fleet or the standalone policy format.

## Tags

| Tag | Effect |
|---|---|
| `configuration` | Run standalone policy configuration |
| `elastic_agent_configuration` | Run standalone policy configuration |
| `certificates` | Run Fleet certificate distribution tasks |
