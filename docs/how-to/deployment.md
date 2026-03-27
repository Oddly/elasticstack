# Deployment Recipes

## Kibana behind a reverse proxy

When Kibana sits behind nginx, Caddy, or a load balancer that terminates TLS, leave Kibana's own TLS off and let the proxy handle HTTPS:

```yaml title="group_vars/kibana.yml"
kibana_tls: false   # default — Kibana serves plain HTTP on :5601

kibana_extra_config:
  server.basePath: "/kibana"           # if proxied under a subpath
  server.rewriteBasePath: true
  server.publicBaseUrl: "https://kibana.example.com/kibana"
```

```nginx title="nginx site config"
upstream kibana {
    server kb1:5601;
    keepalive 16;
}

server {
    listen 443 ssl;
    http2 on;
    server_name kibana.example.com;

    ssl_certificate     /etc/letsencrypt/live/kibana.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/kibana.example.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;

    # Security headers
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location /kibana/ {
        proxy_pass http://kibana/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support (Kibana uses WebSockets for real-time features)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Disable buffering for streaming responses
        proxy_buffering off;
    }
}
```

If you want Kibana itself to serve HTTPS (no proxy), see the next section.

## Kibana with HTTPS enabled (no proxy)

Let the Elasticsearch CA generate and sign a certificate for Kibana:

```yaml title="group_vars/kibana.yml"
kibana_tls: true
kibana_cert_source: elasticsearch_ca   # default — cert signed by the ES CA
```

No additional configuration needed — the role requests a certificate from the CA host, distributes it, and configures `kibana.yml` with the correct paths and passphrases.

## Kibana with external certificates

When you have certificates from an external CA (Let's Encrypt, corporate PKI, etc.):

```yaml title="group_vars/kibana.yml"
kibana_tls: true
kibana_cert_source: external

kibana_tls_cert: /etc/pki/kibana/kibana.crt
kibana_tls_key: /etc/pki/kibana/kibana.key
kibana_tls_ca: /etc/pki/kibana/ca-chain.crt

# Optional: key passphrase if the private key is encrypted
# kibana_tls_key_passphrase: "{{ vault_kibana_key_pass }}"
```

The files must already exist on the Kibana host before running the playbook. The role configures Kibana to use them but does not manage the certificate lifecycle — renewal is your responsibility.

!!! tip
    If your external CA is not the same as the Elasticsearch CA, you also need to configure Elasticsearch to trust it. Add the CA certificate to `elasticsearch_tls_cacerts` on all ES nodes.

## Elasticsearch with external certificates

For environments where certificates come from an external PKI:

```yaml title="group_vars/elasticsearch.yml"
elasticsearch_cert_source: external

# HTTP (client-facing) certificates
elasticsearch_http_tls_cert: /etc/pki/elasticsearch/http.crt
elasticsearch_http_tls_key: /etc/pki/elasticsearch/http.key
elasticsearch_http_tls_ca: /etc/pki/elasticsearch/ca-chain.crt

# Transport (inter-node) certificates
elasticsearch_transport_tls_cert: /etc/pki/elasticsearch/transport.crt
elasticsearch_transport_tls_key: /etc/pki/elasticsearch/transport.key
elasticsearch_transport_tls_ca: /etc/pki/elasticsearch/ca-chain.crt
```

Each node needs its own certificate with the node's hostname or IP in the Subject Alternative Names (SAN). The transport certificate must include all node hostnames since nodes verify each other's identity during cluster formation.

## Standalone Logstash (no Elasticsearch CA)

When Logstash runs independently and doesn't share the Elasticsearch CA:

```yaml title="group_vars/logstash.yml"
elasticstack_full_stack: false
logstash_cert_source: standalone   # self-signed CA + server cert

# Explicit ES hosts since auto-discovery is off
logstash_elasticsearch_hosts:
  - "https://es1.example.com"
  - "https://es2.example.com"
```

In standalone mode, Logstash still creates its `logstash_writer` user and role in Elasticsearch. The `external` mode skips user/role creation entirely.

## Beats shipping directly to Elasticsearch

Skip Logstash entirely and send Beats output straight to ES:

```yaml title="group_vars/beats.yml"
beats_filebeat_output: elasticsearch
beats_auditbeat_output: elasticsearch
beats_metricbeat_output: elasticsearch
beats_security: true   # enable TLS for the ES connection
```

When `beats_security: true`, Beats verifies the Elasticsearch TLS certificate and authenticates with a client certificate. In full-stack mode, the certificate is fetched from the ES CA automatically.

## Air-gapped / offline deployment

When hosts cannot reach `artifacts.elastic.co`:

```yaml title="group_vars/all.yml"
elasticstack_repo_base_url: "https://elastic-cache.internal.example.com"
```

Set up a caching reverse proxy (Nginx, Caddy, Nexus, Artifactory) that mirrors `artifacts.elastic.co` and point this variable at it. The GPG key URL auto-derives from the base URL.

You can also set this as an environment variable:

```bash
export ELASTICSTACK_REPO_BASE_URL=https://elastic-cache.internal.example.com
ansible-playbook -i inventory.yml playbook.yml
```
