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
}

server {
    listen 443 ssl;
    server_name kibana.example.com;

    ssl_certificate     /etc/letsencrypt/live/kibana.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/kibana.example.com/privkey.pem;

    location /kibana/ {
        proxy_pass http://kibana/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

If you want Kibana itself to serve HTTPS (no proxy), see the next section.

## Kibana with HTTPS enabled (no proxy)

```yaml title="group_vars/kibana.yml"
kibana_tls: true
# Auto-generated cert from ES CA (default):
kibana_cert_source: elasticsearch_ca

# Or with an external cert:
# kibana_cert_source: external
# kibana_tls_certificate_file: /etc/pki/kibana/kibana.crt
# kibana_tls_key_file: /etc/pki/kibana/kibana.key
# kibana_tls_ca_file: /etc/pki/kibana/ca.crt
```

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
