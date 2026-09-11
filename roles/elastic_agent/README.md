# Elastic Agent Role

Installs and manages Elastic Agent on Linux from the Elastic package repository. The role supports standalone policies, enrollment into an existing Fleet Server, and self-managed Fleet Server hosts on Elastic Stack 8.x and 9.x.

The role is opt-in because a standalone policy must contain a real output and input, while Fleet enrollment requires a token issued by Kibana. Set `elastic_agent_manage: true` only on hosts where the agent should be installed.

## Standalone mode

Provide the complete standalone policy. Set `elasticstack_full_stack: false` on a host that only runs Elastic Agent, then store credentials or API keys in Ansible Vault or a secrets manager.

```yaml
elasticstack_full_stack: false
elastic_agent_manage: true
elastic_agent_mode: standalone
elastic_agent_standalone_config:
  outputs:
    default:
      type: logstash
      hosts:
        - logstash.example.test:5044
  inputs:
    - type: system/metrics
      id: system-metrics
      data_stream.namespace: default
      streams:
        - metricsets: [cpu, memory]
          data_stream.dataset: system
```

The package flavor marker is read from `elastic_agent_package_flavor_file`,
which defaults to `/opt/Elastic/Agent/.flavor`. The role stops with a clear
error when an existing package's flavor differs from the requested flavor;
purge and reinstall the package to change between `basic` and `servers`.

## Fleet mode

Create an agent policy and enrollment token in Kibana, then pass the Fleet Server URL and token. Set `elastic_agent_fleet_server_ca_source: elasticsearch_ca` when the Fleet Server uses the collection CA, or use `external` with `elastic_agent_fleet_server_ca_file` or `elastic_agent_fleet_server_ca_content` for another CA.

```yaml
elastic_agent_manage: true
elastic_agent_mode: fleet
elastic_agent_fleet_server_url: https://fleet.example.test:8220
elastic_agent_enrollment_token: "{{ vault_fleet_enrollment_token }}"
elastic_agent_fleet_server_ca_source: external
elastic_agent_fleet_server_ca_file: /srv/pki/fleet-server-ca.crt
```

The enrollment fingerprint is stored in `elastic_agent_enrollment_state_file`,
which defaults to `/etc/elastic-agent/.enrollment.sha256`. It lets repeated runs
remain idempotent without persisting the enrollment token. The role also checks
the package-managed encrypted Fleet state at `/etc/elastic-agent/fleet.enc`;
state and marker must both be present for a run to skip enrollment. It refuses
to overwrite an existing Fleet state when the marker is missing or changed, to
avoid creating duplicate Fleet agents. The token and policy content are
suppressed from Ansible output.

## Fleet Server mode

Set `elastic_agent_mode: fleet_server`, install the `servers` package flavor, and provide the Fleet Server policy, Elasticsearch service token, and Elasticsearch URL. The role resolves the Elasticsearch URL from the collection's Elasticsearch inventory group when `elastic_agent_fleet_server_es` is empty, using `elasticsearch_http_publish_host` and `elasticsearch_http_publish_port` when configured and otherwise the inventory address and service port. The Fleet Server policy and service token are created in Kibana or through the Elasticsearch security APIs; this role installs and enrolls the host but does not create Fleet policies.

```yaml
elastic_agent_manage: true
elastic_agent_mode: fleet_server
elastic_agent_package_flavor: servers
elastic_agent_fleet_server_url: https://fleet.example.test:8220
elastic_agent_fleet_server_es: https://es.example.test:9200
elastic_agent_fleet_server_service_token: "{{ vault_fleet_service_token }}"
elastic_agent_fleet_server_policy: fleet-server-policy-id
elastic_agent_fleet_server_ca_source: external
elastic_agent_fleet_server_ca_file: /srv/pki/fleet-server-ca.crt
elastic_agent_fleet_server_es_ca_file: /srv/pki/elasticsearch-ca.crt
elastic_agent_fleet_server_cert_file: /srv/pki/fleet-server.crt
elastic_agent_fleet_server_cert_key_file: /srv/pki/fleet-server.key
```

Certificate files can be read from the controller or the managed host with the matching `*_remote_src` variables. Inline PEM values are available for the CA, certificate, private key, and Elasticsearch CA. Set `elastic_agent_certificate_dir` to change the destination directory. Certificate changes notify the shared service restart lifecycle.

## Migration from Beats

`elastic_agent_migrate_from_beats: true` stops and disables Filebeat, Metricbeat, and Auditbeat before the Agent starts. It leaves their configuration and package files in place so the migration can be reversed. Translate the existing Beat inputs and outputs into a standalone policy or an Agent policy in Kibana before enabling the Agent.
