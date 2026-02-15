# Logstash Role Refactoring Plan

## Overview

Comprehensive refactoring of the Logstash role to provide:
1. Simplified pipeline interface
2. Certificate lifecycle management
3. Elastic Agent input support
4. Manual override options for standalone deployments

## Design Principles

1. **Simpler than raw config**: If Ansible vars require more effort than Logstash config, we've failed
2. **Zero-config defaults**: Works out of the box with sensible defaults
3. **Escape hatches**: Raw Logstash syntax always available
4. **Testable**: Every feature has exhaustive molecule tests

---

## Phase 1: Simplified Pipeline Interface

### New Variables

```yaml
# === Input Configuration ===
logstash_input_beats: true              # Enable beats input (default: true)
logstash_input_beats_port: 5044         # Beats listen port
logstash_input_elastic_agent: false     # Enable elastic_agent input (Phase 3)
logstash_input_elastic_agent_port: 5044 # Agent listen port (same as beats by default)

# === Output Configuration ===
logstash_output_elasticsearch: true     # Enable ES output (default: true)
logstash_elasticsearch_hosts: []        # Override auto-discovery (empty = auto)
logstash_elasticsearch_index: "logstash-%{+YYYY.MM.dd}"

# === Filters (raw Logstash syntax) ===
logstash_filters: ""                    # Inline filter config
logstash_filter_files: []               # List of filter file paths to copy

# === Extra inputs/outputs (raw Logstash syntax) ===
logstash_extra_inputs: ""               # Additional inputs beyond defaults
logstash_extra_outputs: ""              # Additional outputs beyond defaults

# === Full custom pipeline (disables all defaults) ===
logstash_custom_pipeline: ""            # If set, ignores all above, uses this
```

### Pipeline Generation Logic

```
IF logstash_custom_pipeline is set:
    Use it verbatim (full control mode)
ELSE:
    Generate 10-input.conf:
        - beats input (if logstash_input_beats)
        - elastic_agent input (if logstash_input_elastic_agent)
        - logstash_extra_inputs (verbatim)
    
    Generate 50-filter.conf:
        - logstash_filters (verbatim)
        - contents of logstash_filter_files
    
    Generate 90-output.conf:
        - elasticsearch output (if logstash_output_elasticsearch)
        - logstash_extra_outputs (verbatim)
```

### Test Scenarios (molecule/logstash_pipeline_*)

| Scenario | Tests | Verification |
|----------|-------|--------------|
| `logstash_pipeline_defaults` | Zero-config, beats→ES | Service running, config valid, beats port open |
| `logstash_pipeline_filters` | Inline filters | Filter in config, syntax valid |
| `logstash_pipeline_filter_files` | Filter files | Files copied, included in config |
| `logstash_pipeline_extra_io` | Extra inputs/outputs | Both present in config |
| `logstash_pipeline_custom` | Full custom pipeline | Only custom content present |
| `logstash_pipeline_no_defaults` | Disable beats+ES | No default input/output in config |

---

## Phase 2: Certificate Lifecycle Management

### New Variables

```yaml
# === Certificate Source ===
logstash_cert_source: "elasticsearch_ca"  # elasticsearch_ca | standalone | external

# For external certs:
logstash_tls_certificate_file: ""         # Path to server cert
logstash_tls_key_file: ""                 # Path to server key  
logstash_tls_ca_file: ""                  # Path to CA cert

# === Certificate Validity ===
logstash_cert_validity_days: 365          # Cert validity period
logstash_cert_renewal_days: 30            # Renew when this many days left
logstash_cert_auto_renew: true            # Auto-renew on playbook run

# === Force Regeneration ===
logstash_cert_force_regenerate: false     # Force regenerate all certs
```

### Certificate Tasks Flow

```
1. Check cert source mode
2. IF external:
     - Validate provided paths exist
     - Copy to logstash_certs_dir
3. IF elasticsearch_ca OR standalone:
     - Check if certs exist
     - IF exist AND auto_renew:
         - Check expiration
         - IF expiring soon OR force_regenerate:
             - Backup existing certs
             - Generate new certs
     - IF not exist:
         - Generate new certs
4. Configure Logstash to use certs
```

### Test Scenarios (molecule/logstash_certs_*)

| Scenario | Tests | Verification |
|----------|-------|--------------|
| `logstash_certs_elasticsearch_ca` | Certs from ES CA | Certs exist, signed by ES CA, TLS works |
| `logstash_certs_standalone` | Standalone CA | CA created, certs signed, TLS works |
| `logstash_certs_external` | BYO certs | Certs copied, TLS works |
| `logstash_certs_renewal` | Auto-renewal | Create expiring cert, verify renewal |
| `logstash_certs_force_regen` | Force regeneration | New certs generated, old backed up |

---

## Phase 3: Elastic Agent Input Support

### New Variables

```yaml
# === Elastic Agent Input ===
logstash_input_elastic_agent: false       # Enable elastic_agent input
logstash_input_elastic_agent_port: 5044   # Listen port
logstash_input_elastic_agent_ssl: true    # Require TLS (recommended)

# === Agent Client Certificates ===
logstash_agent_client_certs: false        # Generate client certs for agents
logstash_agent_client_certs_output: ""    # Directory on controller to save certs
logstash_agent_client_certs_count: 1      # Number of client certs to generate
```

### elastic_agent Input Template

```ruby
input {
  elastic_agent {
    port => {{ logstash_input_elastic_agent_port }}
    ssl_enabled => {{ logstash_input_elastic_agent_ssl | lower }}
{% if logstash_input_elastic_agent_ssl %}
    ssl_certificate => "{{ logstash_certs_dir }}/{{ inventory_hostname }}-server.crt"
    ssl_key => "{{ logstash_certs_dir }}/{{ inventory_hostname }}-pkcs8.key"
    ssl_certificate_authorities => ["{{ logstash_certs_dir }}/ca.crt"]
    ssl_client_authentication => "required"
{% endif %}
  }
}
```

### Test Scenarios (molecule/logstash_elastic_agent_*)

| Scenario | Tests | Verification |
|----------|-------|--------------|
| `logstash_elastic_agent_basic` | Agent input enabled | Plugin configured, port listening |
| `logstash_elastic_agent_tls` | Agent with TLS | TLS handshake works |
| `logstash_elastic_agent_client_certs` | Client cert generation | Certs generated, output to controller |

---

## Phase 4: Manual Override Options

### New/Clarified Variables

```yaml
# === Elasticsearch Connection ===
logstash_elasticsearch_hosts: []          # Empty = auto-discover from inventory
logstash_elasticsearch_user: ""           # Empty = use logstash_user_name
logstash_elasticsearch_password: ""       # Empty = use logstash_user_password
logstash_elasticsearch_ssl: true          # Use HTTPS
logstash_elasticsearch_ssl_verification: true  # Verify ES cert

# === Credential Management ===
logstash_create_user: true                # Create user in ES
logstash_create_role: true                # Create role in ES
logstash_user_name: "logstash_writer"     # User name
logstash_user_password: "password"        # User password

# === Standalone Mode ===
logstash_standalone: false                # Skip all ES integration
```

### Test Scenarios (molecule/logstash_standalone_*)

| Scenario | Tests | Verification |
|----------|-------|--------------|
| `logstash_standalone_basic` | No ES integration | No ES output, beats input works |
| `logstash_standalone_manual_es` | Manual ES hosts | Provided hosts in config |
| `logstash_standalone_byo_creds` | BYO credentials | User creation skipped, creds used |
| `logstash_standalone_full` | All manual | External ES, BYO creds, BYO certs |

---

## Phase 5: Documentation

### Files to Create/Update

| File | Content |
|------|---------|
| `docs/role-logstash.md` | Complete variable reference |
| `docs/logstash-quickstart.md` | Getting started guide |
| `docs/logstash-certificates.md` | Certificate management guide |
| `docs/logstash-elastic-agent.md` | Elastic Agent integration guide |
| `docs/logstash-standalone.md` | Standalone deployment guide |

---

## Test Matrix Summary

| Category | Scenarios | Total Tests |
|----------|-----------|-------------|
| Pipeline | 6 | ~18 |
| Certificates | 5 | ~15 |
| Elastic Agent | 3 | ~9 |
| Standalone/Override | 4 | ~12 |
| **Total** | **18** | **~54** |

---

## Implementation Order

1. **Phase 1**: Pipeline simplification (builds on PR #67)
2. **Phase 2**: Certificate management (foundational for Phase 3)
3. **Phase 3**: Elastic Agent support (requires Phase 2)
4. **Phase 4**: Manual overrides (independent, can parallelize)
5. **Phase 5**: Documentation (after all features stable)

---

## Migration Notes

### Breaking Changes

- `logstash_pipelines` variable removed (PR #67)
- `logstash_redis_*` variables removed (PR #67)
- `logstash_mermaid*` variables removed (PR #67)

### Deprecated Variables

| Old | New | Notes |
|-----|-----|-------|
| `logstash_elasticsearch_output` | `logstash_output_elasticsearch` | Renamed for consistency |
| `logstash_beats_input` | `logstash_input_beats` | Renamed for consistency |
| `logstash_beats_tls` | `logstash_input_beats_ssl` | Renamed for consistency |

---

## Success Criteria

1. All 18 molecule scenarios pass on all supported platforms
2. Zero-config deployment works (beats→ES with auto-discovery)
3. BYO certs work without modification
4. Cert renewal works automatically
5. Elastic Agent can connect with TLS
6. Standalone deployment works without ES
