# Pipelines & Inputs

## Filebeat with multiple log inputs

```yaml title="group_vars/beats.yml"
beats_filebeat: true
beats_filebeat_log_inputs:
  syslog:
    name: syslog
    paths:
      - /var/log/syslog
      - /var/log/messages
  nginx:
    name: nginx
    paths:
      - /var/log/nginx/access.log
      - /var/log/nginx/error.log
    fields:
      app: nginx
  application:
    name: myapp
    paths:
      - /var/log/myapp/*.log
    fields:
      app: myapp
      env: production
```

## Logstash with complex pipelines

For pipelines that outgrow inline filters, use filter files:

```yaml title="group_vars/logstash.yml"
logstash_filter_files:
  - files/logstash/10-syslog.conf
  - files/logstash/20-nginx.conf
  - files/logstash/30-app.conf
```

Or take full control with `logstash_custom_pipeline`:

```yaml title="group_vars/logstash.yml"
logstash_custom_pipeline: |
  input {
    beats { port => 5044 }
    http { port => 8080 }
  }
  filter {
    if [fields][app] == "nginx" {
      grok { match => { "message" => "%{COMBINEDAPACHELOG}" } }
      geoip { source => "clientip" }
    }
  }
  output {
    if [fields][app] == "nginx" {
      elasticsearch {
        hosts => ["https://es1:9200"]
        index => "nginx-%{+YYYY.MM.dd}"
      }
    } else {
      elasticsearch {
        hosts => ["https://es1:9200"]
        index => "logs-%{+YYYY.MM.dd}"
      }
    }
  }
```
