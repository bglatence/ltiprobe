# ltiprobe

HTTP/DNS/ICMP/TCP/TLS latency measurement tool with SLO validation and CDN detection.
Displays a complete latency distribution (P50 to P99.9) from the terminal.

[![PyPI version](https://badge.fury.io/py/ltiprobe.svg)](https://pypi.org/project/ltiprobe/)

## Installation

```bash
pip install ltiprobe
```

## Usage

```bash
# Sites defined in ltiprobe.yaml (default)
ltiprobe

# Custom sites as arguments
ltiprobe https://apple.com https://amazon.com

# Number of measurements per site
ltiprobe -n 20

# Save results to CSV
ltiprobe --csv

# Show network hop count (traceroute)
ltiprobe --traceroute

# Use an alternate config file
ltiprobe --config-file staging.yaml

# Help
ltiprobe --help
```

## Sample output

```
Measuring response times (10 attempts)...

https://google.com
  HTTP  distribution (10 measurements)
    average :  45.3 ms   min: 28.1   max: 145.2
    p50     :  38.0 ms
    p75     :  45.0 ms
    p90     :  62.0 ms
    p95     :  89.0 ms
    p99     : 145.0 ms
    p99.9   : 145.0 ms
  Stability : stable       (p99/p50 = 3.8x)
  DNS   -> average: 8.2 ms  min: 6.1  max: 11.4

  Network -> 14 hops  good       (≤ 25)  (3 hidden (* * *))

  --- Protocol comparison (cold connection) ---
  ICMP  (network)         :  12.3 ms  min: 11.1  max: 13.5  (10 packets)
  TCP   (port 443)        :  18.7 ms  min: 17.2  max: 21.0  (+6.4 ms)
  TLS   (handshake, ×1)   :  31.2 ms  min: 28.4  max: 35.1  (+12.5 ms)
  HTTP  (p50, cold)       :  38.0 ms  (+6.8 ms)
  HTTP  (p50, keep-alive) :  19.3 ms  ← no TCP/TLS

  ── Cache / CDN ──────────────────────────────────────
  Cache  →  HIT  Cloudflare  PoP: YYZ  Age: 42s

  ── HTTP Validation ──────────────────────────────────
  status_code     200                           →  200               ✓ OK
  body_contains   "google"                      →  found             ✓ OK

  ── SLO Analysis ─────────────────────────────────────
  http_p50_ms        38.0 ms  <=  300 ms        ✓ OK
  http_p95_ms        89.0 ms  <=  400 ms        ✓ OK
  dns_ms              8.2 ms  <=   50 ms        ✓ OK
  ────────────────────────────────────────────────────
  Summary: 3/3 objectives met
```

## Configuration

Create a `ltiprobe.yaml` file at the root of your project:

```yaml
nb_mesures: 10
timeout: 10
langue: EN        # EN or FR

sites:
  - url: https://api.example.com/health
    slo:
      http_p50_ms: 200      # max median HTTP latency
      http_p95_ms: 400      # max HTTP P95 latency
      dns_ms: 50            # max average DNS latency
      tls_ms: 80            # max TLS handshake
      icmp_ms: 30           # max network (ICMP) latency
      tcp_ms: 40            # max TCP handshake
      http_chaud_ms: 150    # max keep-alive HTTP (no TCP/TLS)
      stabilite_ratio: 5    # max P99/P50 ratio
      nb_hops_max: 25       # max network hops (--traceroute)
    assert:
      status_code: 200
      body_contains: "ok"
      header: "Content-Type: application/json"
```

If the file is absent, ltiprobe starts with default sites and values.

### Available SLO keys

| Key | Description |
|---|---|
| `http_p50_ms` | Median HTTP latency (P50) |
| `http_p75_ms` | HTTP P75 latency |
| `http_p90_ms` | HTTP P90 latency |
| `http_p95_ms` | HTTP P95 latency |
| `http_p99_ms` | HTTP P99 latency |
| `http_p999_ms` | HTTP P99.9 latency |
| `dns_ms` | Average DNS latency |
| `tls_ms` | TLS handshake duration |
| `icmp_ms` | Average ICMP network latency |
| `tcp_ms` | TCP handshake duration |
| `http_chaud_ms` | Estimated keep-alive HTTP (no TCP/TLS) |
| `stabilite_ratio` | P99/P50 ratio (e.g. `5` means P99 ≤ 5× P50) |
| `nb_hops_max` | Max network hops (requires `--traceroute`) |

### HTTP response validation (`assert`)

| Key | Description |
|---|---|
| `status_code` | Expected HTTP status code (e.g. `200`) |
| `body_contains` | String expected in the first 4 KB of the body |
| `header` | `"Key: Value"` (partial match) or `"Key"` (presence check) |

## Protocol layer comparison

ltiprobe measures all layers in parallel and shows deltas:

| Layer | What is measured |
|---|---|
| ICMP | Pure network latency (ping) |
| TCP | TCP handshake overhead (connect) |
| TLS | SSL/TLS handshake — **paid once** per connection |
| HTTP cold | Full request (new connection: includes TCP + TLS) |
| HTTP keep-alive | Estimated without TCP/TLS — represents server processing + transfer |

> **Note:** Comparison is done on a *cold connection*. In production with HTTP keep-alive or HTTP/2, only the keep-alive HTTP cost applies per request.

## Stability indicator

ltiprobe computes the P99/P50 ratio to assess latency consistency:

| Ratio | Interpretation |
|---|---|
| < 2x | Very stable — all users have a similar experience |
| 2x – 5x | Stable — some acceptable variation |
| 5x – 10x | Variable — noticeable latency spikes |
| > 10x | Unstable — some users experience very high latency |

## Network hop indicator (`--traceroute`)

| Hops | Indicator |
|---|---|
| ≤ 15 | Excellent — very direct route |
| ≤ 25 | Good — normal routing |
| ≤ 35 | High — long route (typically intercontinental) |
| > 35 | Critical — suboptimal route or routing issue |

Hidden hops (`* * *`) are counted but reported separately.

## CDN / cache detection

ltiprobe automatically sends a HEAD request in parallel and reads response headers
to detect whether the response comes from a CDN cache or the origin server.

| CDN detected | Header analysed |
|---|---|
| Cloudflare | `CF-Ray` |
| CloudFront (AWS) | `X-Amz-Cf-Pop` |
| Fastly | `X-Served-By` |
| Akamai | `X-Check-Cacheable` |
| Varnish | `Via` |

## Multi-environment profiles (`--config-file`)

```bash
ltiprobe --config-file prod.yaml
ltiprobe --config-file staging.yaml
```

## Multilingual support

Set `langue: EN` or `langue: FR` in `ltiprobe.yaml`.

## CSV export

With `--csv`, ltiprobe generates a timestamped file containing columns
`average`, `min`, `max`, `p50` through `p999`, `dns_moyenne`, and `hdr_encode`
(compressed histogram replayable with the [HdrHistogram](https://github.com/HdrHistogram/HdrHistogram_py) library).

## License

MIT

---

## Français

Outil de mesure de latence HTTP/DNS/ICMP/TCP/TLS avec validation de SLOs et détection CDN.
Affiche une distribution complète des latences (P50 à P99.9) depuis le Terminal.

### Installation

```bash
pip install ltiprobe
```

### Utilisation

```bash
ltiprobe                              # Sites définis dans ltiprobe.yaml
ltiprobe https://apple.com            # Site personnalisé
ltiprobe -n 20                        # 20 mesures par site
ltiprobe --csv                        # Export CSV
ltiprobe --traceroute                 # Afficher les hops réseau
ltiprobe --config-file staging.yaml   # Fichier de config alternatif
```

### Configuration (`ltiprobe.yaml`)

```yaml
nb_mesures: 10
timeout: 10
langue: FR        # FR ou EN

sites:
  - url: https://api.exemple.com/health
    slo:
      http_p50_ms: 200
      http_p95_ms: 400
      dns_ms: 50
    assert:
      status_code: 200
      body_contains: "ok"
```

### Clés SLO disponibles

| Clé | Description |
|---|---|
| `http_p50_ms` | Latence HTTP médiane (P50) |
| `http_p95_ms` | Latence HTTP P95 |
| `dns_ms` | Latence DNS moyenne |
| `tls_ms` | Durée du handshake TLS |
| `icmp_ms` | Latence réseau ICMP |
| `tcp_ms` | Durée du handshake TCP |
| `http_chaud_ms` | HTTP keep-alive estimé (sans TCP/TLS) |
| `stabilite_ratio` | Ratio P99/P50 |
| `nb_hops_max` | Hops réseau max (requiert `--traceroute`) |

### Licence

MIT
