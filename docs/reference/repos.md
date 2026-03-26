# repos

Ansible role for configuring Elastic Stack package repositories. Sets up APT or YUM repositories and imports the Elastic GPG signing key. This role must run before any other role in the collection so that packages are available for installation.

The role has no service to manage — it only configures the package manager. It delegates to the shared `elasticstack` role for defaults (base URL, release version, GPG key URL).

## Task flow

```mermaid
graph TD
    A[Include shared defaults] --> B{OS family?}
    B -->|Debian| C[Install gpg + gpg-agent]
    B -->|RedHat| D[Install gnupg]


    C --> F[Download GPG key to<br/>/usr/share/keyrings/elasticsearch.asc]
    F --> G[Remove legacy repo files<br/>7.x, 8.x, 9.x]
    G --> H[Configure apt repository]

    D --> I{EL 9+?}
    I -->|Yes| J{rpm_workaround?}
    J -->|Yes| K[Set crypto-policies LEGACY]
    J -->|No| L[Show warning]
    I -->|No| M[Import RPM GPG key]
    K --> M
    L --> M
    M --> N[Configure yum repository]

    style K fill:#ff9800,stroke:#333,color:#fff
    style G fill:#f44336,stroke:#333,color:#fff
```

## Requirements

- Minimum Ansible version: `2.18`

## What it does per OS family

### Debian / Ubuntu

1. Installs `gpg` and `gpg-agent` packages
2. Downloads the Elastic GPG key to `/usr/share/keyrings/elasticsearch.asc`
3. Removes legacy repository files from previous major versions (cleans up `/etc/apt/sources.list.d/artifacts_elastic_co_packages_{7,8,9}_x_apt.list`)
4. Configures the APT repository with signed-by pointing at the downloaded keyring:
   ```
   deb [signed-by=/usr/share/keyrings/elasticsearch.asc] <base_url>/packages/<release>.x/apt stable main
   ```

### RedHat / Rocky Linux / RHEL

1. Installs `gnupg`
2. On EL 9+, applies a crypto-policy workaround (see below)
3. Imports the Elastic RPM GPG key via `rpm_key`
4. Configures the YUM repository at `<base_url>/packages/<release>.x/yum`

## EL 9+ crypto-policy workaround

!!! note
    RHEL 9 and derivatives ship with stricter default crypto policies that can prevent RPM signature verification of older Elastic packages ([elasticsearch#85876](https://github.com/elastic/elasticsearch/issues/85876)).

The workaround runs `update-crypto-policies --set LEGACY` to relax the policy. This is gated behind `elasticstack_rpm_workaround` — if you're on EL 9+ and don't enable it, the role prints a debug warning but continues. Enable it if RPM key import fails:

```yaml
elasticstack_rpm_workaround: true
```

!!! warning
    Setting LEGACY crypto policies weakens system-wide TLS and cipher requirements. Consider applying this only on initial setup and reverting afterward, or using a more targeted policy override.

## Legacy repository cleanup

On Debian, the role removes old-format repository files for versions 7, 8, and 9. This prevents `apt update` conflicts when switching between major versions or when the repository file naming convention has changed from earlier versions of this collection.

## Default Variables

All repository configuration comes from the shared `elasticstack` role defaults. The repos role has no defaults of its own. The relevant shared variables are:

```yaml
elasticstack_release: 8
elasticstack_repo_base_url: "{{ lookup('env', 'ELASTICSTACK_REPO_BASE_URL') | default('https://artifacts.elastic.co', true) }}"
elasticstack_repo_key: "{{ elasticstack_repo_base_url }}/GPG-KEY-elasticsearch"
elasticstack_enable_repos: true
elasticstack_rpm_workaround: false
```

`elasticstack_release`
:   Major version (`8` or `9`) — determines which repository URL is configured.

`elasticstack_repo_base_url`
:   Base URL for package repos. Override for mirrors or air-gapped environments. Also reads from the `ELASTICSTACK_REPO_BASE_URL` environment variable.

`elasticstack_repo_key`
:   GPG key URL for package verification. Derived from the base URL by default.

`elasticstack_enable_repos`
:   Whether the YUM repo is marked `enabled`. APT repos are always present once added. Set to `false` if you manage repositories externally.

`elasticstack_rpm_workaround`
:   Apply the EL 9+ crypto-policy workaround described above.

See [elasticstack](elasticstack.md) for full documentation of these variables.

## Tags

This role does not define any tags.

## License

GPL-3.0-or-later
