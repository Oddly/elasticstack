# Performance Tuning

## JVM heap sizing

The Elasticsearch role auto-calculates heap from physical RAM using the formula `min(RAM/2, 30GB)` with a 1GB floor. For production, set it explicitly:

```yaml
elasticsearch_heap: "16"   # in GB
```

The 30GB cap exists because beyond that, the JVM switches from 4-byte compressed ordinary object pointers (compressed OOPs) to 8-byte pointers, which wastes heap and reduces effective capacity.

Logstash heap is set separately:

```yaml
logstash_heap: "1g"   # default: 1g
```

## Memory locking

Prevent Elasticsearch from swapping to disk:

```yaml
elasticsearch_memory_lock: true
```

This sets `bootstrap.memory_lock: true` in `elasticsearch.yml` and configures systemd to allow unlimited memory locking. Essential for production — swapping causes GC pauses that look like node failures to the cluster.

## JVM garbage collection tuning

Elasticsearch 8.x+ uses G1GC by default with well-tuned parameters. Only add custom JVM flags if you've profiled your specific workload and have evidence that defaults aren't optimal:

```yaml
elasticsearch_jvm_custom_parameters:
  - "-XX:MaxGCPauseMillis=200"
  - "-XX:InitiatingHeapOccupancyPercent=75"
```

## Thread pool sizing

Thread pool sizes are auto-tuned by Elasticsearch based on CPU count. Only adjust queue sizes if you see `rejected_execution_exception` errors in logs:

```yaml
elasticsearch_extra_config:
  thread_pool.search.queue_size: 2000  # default: 1000
  thread_pool.write.queue_size: 500    # default: 200
```

Increasing queue sizes trades memory for burst capacity. If queues are consistently full, the cluster needs more nodes — larger queues just delay the rejection.

## Disk watermarks

Control when Elasticsearch stops allocating shards based on disk usage:

```yaml
elasticsearch_cluster_settings:
  cluster.routing.allocation.disk.watermark.low: "85%"     # stop allocating new shards
  cluster.routing.allocation.disk.watermark.high: "90%"    # start relocating shards away
  cluster.routing.allocation.disk.watermark.flood_stage: "95%"  # read-only indices
```

These are dynamic settings applied via the cluster settings API — no restart needed.

## Recovery throttling

Limit how much bandwidth shard recovery uses (prevents recovery from saturating the network):

```yaml
elasticsearch_cluster_settings:
  indices.recovery.max_bytes_per_sec: "100mb"   # default: 40mb
```

Increase this on fast networks to speed up recovery after a node restart.

## Logstash pipeline tuning

Pipeline workers, batch size, and batch delay are tuned directly in `logstash.yml` via `logstash_extra_config` since they vary by workload:

```yaml
logstash_extra_config:
  pipeline.workers: 4        # default: cpu_count
  pipeline.batch.size: 250   # default: 125
  pipeline.batch.delay: 50   # default: 50 (ms)
```

Increase `pipeline.batch.size` for throughput-oriented workloads. Decrease it for latency-sensitive pipelines.

### Persistent queues

The role defaults to persistent queues (`logstash_queue_type: persisted`) for durability — events survive Logstash restarts. Increase the queue size for high-throughput pipelines:

```yaml
logstash_queue_max_bytes: "4gb"   # default: 1gb
```

Persistent queues write to disk, so use fast storage (SSD/NVMe). Monitor queue depth via the Logstash monitoring API (`GET /_node/stats/pipelines`).
