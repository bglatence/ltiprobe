# ltiprobe

HTTP/DNS/ICMP/TCP/TLS latency measurement tool with SLO validation, jitter, packet loss, MOS score (ITU-T G.107), CDN detection, Path MTU discovery, Prometheus export and webhook alerting.
Displays a complete latency distribution (P50 to P99.9) from the terminal.

[![PyPI version](https://img.shields.io/pypi/v/ltiprobe)](https://pypi.org/project/ltiprobe/)

## Installation

### macOS

```bash
# Option 1 — Homebrew (recommended, no Python required)
brew tap bglatence/ltiprobe
brew install ltiprobe

# Option 2 — pip
pip install ltiprobe
```

### Linux

On Linux, use **pipx** — it installs CLI tools in an isolated environment and configures PATH automatically:

```bash
# Install pipx (once)
sudo apt install pipx        # Debian / Ubuntu
pipx ensurepath              # adds ~/.local/bin to PATH
source ~/.bashrc

# Install ltiprobe
pipx install ltiprobe
ltiprobe --version
```

> **Why not plain `pip install`?**
> Without a virtual environment, `pip` installs scripts in `~/.local/bin` which is often not in PATH on Linux.
> Using `pipx` avoids this entirely.

If you prefer `pip`, add `~/.local/bin` to your PATH first:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
pip install ltiprobe
```

### Windows

```bash
pip install ltiprobe
ltiprobe --version
```

## Usage

```bash
# Sites defined in ltiprobe.yaml (default)
ltiprobe

# DNS name or IP address as argument
ltiprobe https://apple.com https://amazon.com
ltiprobe http://192.168.1.100
ltiprobe https://10.0.0.5

# Number of measurements per site
ltiprobe -n 20

# Save results to CSV
ltiprobe --csv

# Show network hop count (traceroute)
ltiprobe --traceroute

# Hop-by-hop analysis with jitter and loss per hop
ltiprobe --traceroute-detail

# Discover the effective Path MTU to each site
ltiprobe --path-mtu

# Output verbosity: basic (HTTP/DNS/SLO only) or full (all sections, default)
ltiprobe --verbosity basic

# Continuous monitoring — re-run every 60 seconds
ltiprobe --interval 60

# Compare against a baseline CSV
ltiprobe --baseline resultats_20260420_143200.csv

# Export metrics in Prometheus text format
ltiprobe --prometheus-out metrics.prom

# Show advanced TLS certificate information
ltiprobe --tls-info

# Use an alternate config file
ltiprobe --config-file staging.yaml

# Disable TLS certificate validation (self-signed cert or direct IP)
ltiprobe --no-verify-tls https://10.0.0.5

# Help
ltiprobe --help
```

> **DNS name or IP address**: ltiprobe accepts both. When using an IP address directly,
> DNS measurement is skipped (shown as N/A) and reachability is verified before starting.
> Use `--no-verify-tls` when the server uses a self-signed certificate.

## Sample output

```
ltiprobe (1.5.0):

* measuring response times of web sites (10 attempts)
* using config file: ltiprobe.yaml

── Network ──────────────────────────────────────────
  en0     Wi-Fi                          ← measuring
  en1     USB 10/100/1000 LAN
  en2     Thunderbolt Ethernet
  Local IP    →  192.168.1.45
  Public IP   →  203.0.113.42
  ISP         →  Bell Canada
  AS          →  AS577 Bell Canada
  Country     →  Canada (CA)

── ltiprobe measures ────────────────────────────────────────

https://google.com
  HTTP  distribution (10 measurements)
    average :  45.3 ms   min: 28.1   max: 145.2
    p50     :  38.0 ms
    p75     :  45.0 ms
    p90     :  62.0 ms
    p95     :  89.0 ms
    p99     : 145.0 ms
    p99.9   : 145.0 ms
  HTTP  timing (p50)
    TTFB       : 29.1 ms  ← server processing
    Transfer   :  8.9 ms  ← content download
    Total p50  : 38.0 ms
  Stability : stable       (p99/p50 = 3.8x)
  DNS   -> average: 8.2 ms  min: 6.1  max: 11.4

  ── DNS Cache ────────────────────────────────────────
  Network  →  8.2 ms
  OS cache →  0.3 ms
  TTL      →  300s

  --- Protocol comparison (cold connection) ---
  ICMP  (network)         :  12.3 ms  min: 11.1  max: 13.5  jitter: 1.2 ms  loss: 0%  (10 packets)
  TCP   (port 443)        :  18.7 ms  min: 17.2  max: 21.0  jitter: 0.8 ms  (+6.4 ms)
  TLS   (handshake, ×1)   :  31.2 ms  min: 28.4  max: 35.1  jitter: 1.5 ms  (+12.5 ms)
  HTTP  (p50, cold)       :  38.0 ms  (+6.8 ms)
  HTTP  (p50, keep-alive) :  19.3 ms  ← no TCP/TLS

  ── Scoring Standards ────────────────────────────────
  ITU-T G.107 (E-Model)
    R-factor  : 88.1 / 100
    MOS       :  4.3 / 4.5  ✓  excellent

  ── Traceroute hop-by-hop (5 probes/hop) ─────────────
  Hop  1  192.168.1.1       1.2 ms  jitter:  0.3 ms  loss:  0%
  Hop  2  10.20.3.1         8.4 ms  jitter:  2.1 ms  loss:  0%   ⚠ jitter
  Hop  3  *                 silent (ICMP blocked)
  Hop  4  72.14.204.1       9.1 ms  jitter:  0.4 ms  loss:  0%
  Hop  5  142.250.74.46    11.3 ms  jitter:  0.3 ms  loss:  0%
  ✓ destination reached in 5 hops

  ── Path MTU ─────────────────────────────────────────
  MTU       →  1500 bytes  standard Ethernet
  Probes    →  1

  ── Cache / CDN ──────────────────────────────────────
  Cache  →  HIT  Cloudflare  PoP: YYZ  Age: 42s

  ── TLS Certificate ──────────────────────────────────
  Version     : TLSv1.3
  Cipher      : TLS_AES_128_GCM_SHA256
  Issuer      : Google Trust Services
  Subject (CN): *.google.com
  Expires on  : 2026-08-18  (in 113 days)  ✓
  HSTS        : max-age=31536000

  ── HTTP Validation ──────────────────────────────────
  status_code     200                           →  200               ✓ OK
  body_contains   "google"                      →  found             ✓ OK

  ── SLO Analysis ─────────────────────────────────────
  http_p50_ms        38.0 ms  <=  300.0 ms      ✓ OK
  http_p95_ms        89.0 ms  <=  400.0 ms      ✓ OK
  dns_ms              8.2 ms  <=   50.0 ms      ✓ OK
  mos_min             4.3     >=    3.6          ✓ OK
  ────────────────────────────────────────────────────
  Summary: 4/4 objectives met
```

## Configuration

Create a `ltiprobe.yaml` file at the root of your project:

```yaml
nb_mesures: 10
timeout: 10
langue: EN        # EN, FR, ES, DE, JA or ZH
verbosity: full   # full (default) or basic

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
      stability_ratio: 5    # max P99/P50 ratio
      nb_hops_max: 25       # max network hops (--traceroute)
      mos_min: 3.6          # min MOS score 1.0–4.5 (ITU-T G.107)
    assert:
      status_code: 200
      body_contains: "ok"
      header: "Content-Type: application/json"

webhook:
  url: https://hooks.slack.com/services/xxx/yyy/zzz
  on: slo_violation         # slo_violation | degradation | all
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
| `icmp_jitter_ms` | ICMP jitter (RTT standard deviation) |
| `icmp_loss_pct` | ICMP packet loss percentage |
| `tcp_ms` | TCP handshake duration |
| `tcp_jitter_ms` | TCP jitter |
| `http_chaud_ms` | Estimated keep-alive HTTP (no TCP/TLS) |
| `stability_ratio` | P99/P50 ratio (e.g. `5` means P99 ≤ 5× P50) |
| `nb_hops_max` | Max network hops (requires `--traceroute`) |
| `mos_min` | Minimum MOS score 1.0–4.5 — inverted check: fails if MOS **below** threshold |

### HTTP response validation (`assert`)

| Key | Description |
|---|---|
| `status_code` | Expected HTTP status code (e.g. `200`) |
| `body_contains` | String expected in the first 4 KB of the body |
| `header` | `"Key: Value"` (partial match) or `"Key"` (presence check) |

## Network section

At startup, ltiprobe detects and displays your network context before any measurement:

- All available interfaces with their type (Wi-Fi, Ethernet, VPN…) — the active one is highlighted
- Local IP address (via active interface)
- Public IP address, ISP, AS number and country (via ip-api.com)

This makes it easy to identify **from which network** the measurements were taken — useful when comparing results across locations or after a network change.

## DNS Cache / TTL detection

For each site, ltiprobe measures DNS resolution at two levels:

| Metric | What it measures |
|---|---|
| **Network** | Full DNS resolution bypassing the OS cache — reflects actual resolver latency |
| **OS cache** | Second resolution via the OS — shown in green when < 30% of network time (cache is effective) |
| **TTL** | Time-to-live reported by the authoritative server |

A very low cache time (< 1 ms) confirms the OS cache is active. A TTL of 60s or less may cause frequent cache misses under load.

## TTFB / Transfer decomposition

ltiprobe splits each HTTP measurement into two phases with no extra request:

| Phase | What it measures |
|---|---|
| **TTFB** (Time To First Byte) | Time until the server sends the first response byte — reflects server processing and network round-trip |
| **Transfer** | Time to download the response body — reflects content size and bandwidth |

Both values are reported at P50 across all measurements.

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

## Jitter and packet loss

ltiprobe reports jitter and packet loss for each protocol layer:

| Metric | Description |
|---|---|
| **Jitter** | Standard deviation of round-trip times — reflects latency consistency |
| **Packet loss** | Percentage of ICMP packets lost — displayed in green (0%) or orange (> 0%) |

Jitter is available on ICMP, TCP and TLS. Packet loss is available on ICMP only (TCP handles retransmission transparently).

## Scoring Standards

ltiprobe includes a **Scoring Standards** section that applies industry-standard quality models
to the measured network metrics. It appears automatically when ICMP data is available.

### ITU-T G.107 (E-Model)

The E-Model is the ITU-T standard for estimating voice and real-time communication quality
from three network metrics: latency, jitter, and packet loss.

**Inputs** (all already measured by ltiprobe):

| Input | Source |
|---|---|
| Latency | ICMP mean RTT |
| Jitter | ICMP RTT standard deviation |
| Packet loss | ICMP loss % |

**Output**:

- **R-factor** (0–100): raw quality score — higher is better
- **MOS** (1.0–4.5): Mean Opinion Score — perceptual quality as experienced by end users

| MOS | R-factor | Quality | User experience |
|---|---|---|---|
| ≥ 4.3 | ≥ 90 | Excellent | Indistinguishable from face-to-face |
| ≥ 4.0 | ≥ 80 | Good | Minor imperceptible imperfections |
| ≥ 3.6 | ≥ 70 | Acceptable | Noticeable but tolerable |
| ≥ 3.1 | ≥ 60 | Poor | Significant effort required |
| < 3.1 | < 60 | Bad | Communication breakdown |

> **Reference codec**: G.711 (standard telephone quality, widely used for VoIP).

Use `mos_min` in your SLO configuration to enforce a minimum quality threshold. Unlike other SLO keys (which set a maximum), `mos_min` triggers a violation when the MOS score **falls below** the threshold.

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

## Hop-by-hop analysis (`--traceroute-detail`)

`--traceroute-detail` goes further than `--traceroute`: it sends **5 probes per hop** and reports latency, jitter, and packet loss at each intermediate router.

```
── Traceroute hop-by-hop (5 probes/hop) ─────────────
  Hop  1  192.168.1.1       1.2 ms  jitter:  0.3 ms  loss:  0%
  Hop  2  10.20.3.1         8.4 ms  jitter:  2.1 ms  loss:  0%   ⚠ jitter
  Hop  3  *                 silent (ICMP blocked)
  Hop  4  72.14.204.1       9.1 ms  jitter:  0.4 ms  loss:  0%
  ✓ destination reached in 4 hops
```

This lets you **pinpoint where degradation originates** — a jitter spike at hop 2 means the issue is at your ISP's aggregation layer, not at the destination server. Silent hops (routers that block ICMP TTL-exceeded) are displayed without error.

Alerts:
- **⚠ jitter** — hop jitter ≥ 2 ms
- **⚠ loss** — at least one probe lost at this hop

Runs in parallel with all other probes. Only shown in `--verbosity full`.

## Path MTU Discovery (`--path-mtu`)

`--path-mtu` discovers the effective **Maximum Transmission Unit** on the path to each site using a binary search with the DF bit set (Don't Fragment). No raw socket or `sudo` required — uses `ping -D` on macOS and `ping -M do` on Linux.

```
── Path MTU ─────────────────────────────────────────
  MTU       →  1500 bytes  standard Ethernet
  Probes    →  1
```

| MTU range | Label | Typical cause |
|---|---|---|
| ≥ 1480 bytes | standard Ethernet | Normal — no tunneling |
| 1400–1479 bytes | reduced (VPN / tunnel likely) | IPsec or OpenVPN overhead |
| < 1400 bytes | minimal (PPPoE / degraded link) | PPPoE, GRE, or broken PMTUD |

**PMTUD blackhole**: when routers silently drop DF-bit packets instead of sending an ICMP "Fragmentation Needed" reply, TCP connections stall for large transfers. ltiprobe detects and reports this condition explicitly.

Only shown in `--verbosity full`.

## Output verbosity (`--verbosity`)

Control how much detail is shown:

| Level | Sections shown |
|---|---|
| `basic` | HTTP distribution, DNS latency, SLO analysis |
| `full` (default) | All of the above + HTTP timing, DNS cache/TTL, protocol comparison, scoring, traceroute, path MTU, CDN, TLS certificate, assertions |

Set the default in `ltiprobe.yaml`:

```yaml
verbosity: basic
```

Or override on the command line:

```bash
ltiprobe --verbosity basic
ltiprobe --verbosity full
```

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

## Advanced TLS information (`--tls-info`)

With `--tls-info`, ltiprobe inspects the TLS certificate and security configuration of each HTTPS site:

- TLS version and cipher suite negotiated
- Certificate issuer and subject (CN)
- Expiry date — with an **orange warning** if fewer than 30 days remain, **red** if expired
- HSTS header presence and value

The inspection reuses the existing TLS handshake thread — no extra network connection.

## Continuous monitoring (`--interval`)

```bash
ltiprobe --interval 60        # re-run every 60 seconds
ltiprobe --interval 30 --csv  # accumulate results across all scans into one CSV
```

Each scan is timestamped with local time + UTC:

```
── Scan #3  14:32 EDT / 18:32 UTC ────────────────────────
```

A degradation alert fires when a metric increases by **≥ 50%** vs the previous scan:

```
  ⚠  p50 : 38ms → 72ms (+89%)  since 14:28 EDT
```

**Coordinated omission correction** (Gil Tene): when `--interval` is set, ltiprobe applies HDR histogram corrected recording to prevent slow-server bias from masking high-percentile latency. P99 and P99.9 reflect the true user experience under a fixed measurement rate.

## Baseline comparison (`--baseline`)

Compare current results against a previously saved CSV:

```bash
# Save a baseline
ltiprobe --csv

# Compare later
ltiprobe --baseline resultats_20260420_143200.csv

# Compare and export a diff CSV
ltiprobe --baseline resultats_20260420_143200.csv --csv
```

When `--baseline` and `--csv` are combined, a second file `comparaison_*.csv` is generated
with columns `{metric}_avant`, `{metric}_apres`, `{metric}_delta_pct`, `{metric}_statut`
for each site.

Baselines generated by `--interval` (multiple rows per URL) are automatically aggregated
by **median**, making the reference robust to transient spikes.

Regression threshold: **+10%** or more on HTTP P50, P95, P99, DNS, or TTFB.

## Prometheus export (`--prometheus-out`)

```bash
ltiprobe --prometheus-out metrics.prom
```

Generates a Prometheus text format file compatible with
[node_exporter textfile collector](https://github.com/prometheus/node_exporter#textfile-collector)
and Pushgateway.

Exported metrics:

| Metric | Description |
|---|---|
| `ltiprobe_http_p50_ms` | HTTP P50 latency |
| `ltiprobe_http_p95_ms` | HTTP P95 latency |
| `ltiprobe_http_p99_ms` | HTTP P99 latency |
| `ltiprobe_http_moyenne_ms` | HTTP mean latency |
| `ltiprobe_ttfb_p50_ms` | TTFB P50 |
| `ltiprobe_transfert_p50_ms` | Transfer time P50 |
| `ltiprobe_dns_moyenne_ms` | DNS mean latency |
| `ltiprobe_icmp_ms` | ICMP mean RTT |
| `ltiprobe_tcp_ms` | TCP handshake mean |
| `ltiprobe_tls_ms` | TLS handshake mean |
| `ltiprobe_stability_ratio` | P99/P50 stability ratio |
| `ltiprobe_slo_ok` | SLO check result — `1.0` = met, `0.0` = violated (labels: `url`, `slo`) |

## Webhook alerting

Configure a webhook in `ltiprobe.yaml` to receive HTTP POST notifications:

```yaml
webhook:
  url: https://hooks.slack.com/services/xxx/yyy/zzz
  on: slo_violation   # slo_violation | degradation | all
```

| `on` value | When it fires |
|---|---|
| `slo_violation` | When at least one SLO check fails (default) |
| `degradation` | When a metric degrades ≥ 50% vs previous scan (`--interval`) |
| `all` | Both of the above |

Payload sent (JSON):

```json
{
  "source": "ltiprobe",
  "event": "slo_violation",
  "url": "https://apple.com",
  "heure": "14:32 EDT",
  "violations": [
    {"slo": "http_p50_ms", "valeur": 312.5, "seuil": 200}
  ]
}
```

The webhook call is non-blocking (daemon thread) and does not affect measurement timing.
Compatible with Slack, Microsoft Teams, PagerDuty, Discord, and any HTTP endpoint.

## Multi-environment profiles (`--config-file`)

```bash
ltiprobe --config-file prod.yaml
ltiprobe --config-file staging.yaml
```

## Multilingual support

Set `langue: EN`, `langue: FR`, `langue: ES`, `langue: DE`, `langue: JA` or `langue: ZH` in `ltiprobe.yaml`.

## CSV export (`--csv`)

Generates a timestamped file `resultats_YYYYMMDD_HHMMSS.csv` with columns:
`url`, `average`, `min`, `max`, `p50` through `p999`, `dns_moyenne`, `ttfb_p50`,
`transfert_p50`, and `hdr_encode` (compressed histogram replayable with the
[HdrHistogram](https://github.com/HdrHistogram/HdrHistogram_py) library).

## License

MIT

---

## Français

Outil de mesure de latence HTTP/DNS/ICMP/TCP/TLS avec validation de SLOs, détection CDN, découverte du Path MTU, export Prometheus et alertes webhook.
Affiche une distribution complète des latences (P50 à P99.9) depuis le terminal.

### Installation

**macOS**
```bash
brew tap bglatence/ltiprobe && brew install ltiprobe
# ou
pip install ltiprobe
```

**Linux** — utiliser `pipx` pour éviter les problèmes de PATH :
```bash
sudo apt install pipx && pipx ensurepath && source ~/.bashrc
pipx install ltiprobe
```

**Windows**
```bash
pip install ltiprobe
```

### Utilisation

```bash
ltiprobe                                           # Sites définis dans ltiprobe.yaml
ltiprobe https://apple.com                         # Nom DNS
ltiprobe http://192.168.1.100                      # Adresse IP directe
ltiprobe --no-verify-tls https://10.0.0.5          # IP avec cert auto-signé
ltiprobe -n 20                                     # 20 mesures par site
ltiprobe --csv                                     # Export CSV
ltiprobe --traceroute                              # Nombre de hops réseau
ltiprobe --traceroute-detail                       # Analyse hop-by-hop (jitter + loss par saut)
ltiprobe --path-mtu                                # Découverte du Path MTU effectif
ltiprobe --verbosity basic                         # Affichage réduit (HTTP/DNS/SLO seulement)
ltiprobe --interval 60                             # Monitoring continu toutes les 60s
ltiprobe --baseline resultats_20260420_143200.csv  # Comparer à une baseline
ltiprobe --prometheus-out metrics.prom             # Export Prometheus
ltiprobe --tls-info                                # Informations TLS avancées
ltiprobe --config-file staging.yaml               # Fichier de config alternatif
```

> **Nom DNS ou adresse IP** : les deux sont acceptés. En mode IP, la mesure DNS est
> ignorée (affiché N/A) et la joignabilité est vérifiée avant le démarrage.

### Configuration (`ltiprobe.yaml`)

```yaml
nb_mesures: 10
timeout: 10
langue: FR        # FR, EN, ES, DE, JA ou ZH
verbosity: full   # full (défaut) ou basic

sites:
  - url: https://api.exemple.com/health
    slo:
      http_p50_ms: 200
      http_p95_ms: 400
      dns_ms: 50
      mos_min: 3.6      # MOS minimum (ITU-T G.107) — violation si en dessous
    assert:
      status_code: 200
      body_contains: "ok"

webhook:
  url: https://hooks.slack.com/services/xxx/yyy/zzz
  on: slo_violation   # slo_violation | degradation | all
```

### Clés SLO disponibles

| Clé | Description |
|---|---|
| `http_p50_ms` | Latence HTTP médiane (P50) |
| `http_p75_ms` | Latence HTTP P75 |
| `http_p90_ms` | Latence HTTP P90 |
| `http_p95_ms` | Latence HTTP P95 |
| `http_p99_ms` | Latence HTTP P99 |
| `http_p999_ms` | Latence HTTP P99.9 |
| `dns_ms` | Latence DNS moyenne |
| `tls_ms` | Durée du handshake TLS |
| `icmp_ms` | Latence réseau ICMP |
| `icmp_jitter_ms` | Jitter ICMP (écart-type des RTT) |
| `icmp_loss_pct` | Taux de perte ICMP |
| `tcp_ms` | Durée du handshake TCP |
| `tcp_jitter_ms` | Jitter TCP |
| `http_chaud_ms` | HTTP keep-alive estimé (sans TCP/TLS) |
| `stability_ratio` | Ratio P99/P50 |
| `nb_hops_max` | Hops réseau max (requiert `--traceroute`) |
| `mos_min` | Score MOS minimum 1.0–4.5 — violation si MOS **en dessous** du seuil |

### Section Réseau

Au démarrage, ltiprobe détecte et affiche le contexte réseau avant toute mesure : toutes les interfaces disponibles (Wi-Fi, Ethernet, VPN…) avec l'interface active en surbrillance, l'IP locale, l'IP publique, le FAI, le numéro AS et le pays.

### Cache DNS / TTL

Pour chaque site, ltiprobe mesure la résolution DNS à deux niveaux : résolution réseau complète (en contournant le cache OS) et résolution via le cache OS. Le TTL rapporté par le serveur faisant autorité est également affiché.

### Analyse hop-by-hop (`--traceroute-detail`)

Envoie 5 sondages par saut et calcule la latence, le jitter et le taux de perte à chaque routeur intermédiaire. Permet de **localiser précisément** l'origine d'une dégradation. Les routeurs silencieux (ICMP TTL-exceeded bloqué) sont affichés sans erreur.

Alertes par saut : `⚠ jitter` si jitter ≥ 2 ms, `⚠ loss` si perte > 0%.

### Découverte du Path MTU (`--path-mtu`)

Découvre le MTU effectif vers chaque site par recherche binaire avec le bit DF activé. Sans raw socket ni `sudo`. Détecte les PMTUD blackholes (routeurs qui bloquent silencieusement les paquets DF au lieu d'envoyer un ICMP "Fragmentation Needed").

| MTU | Indication |
|---|---|
| ≥ 1480 octets | standard Ethernet |
| 1400–1479 octets | réduit (VPN / tunnel probable) |
| < 1400 octets | minimal (PPPoE / lien dégradé) |

### Visibilité des sections (`--verbosity`)

| Niveau | Sections affichées |
|---|---|
| `basic` | Distribution HTTP, DNS, analyse SLO |
| `full` (défaut) | Tout + timing HTTP, cache DNS/TTL, comparaison protocoles, scoring, traceroute, Path MTU, CDN, certificat TLS, assertions |

### TTFB / décomposition du transfert

ltiprobe décompose chaque mesure HTTP en deux phases sans requête supplémentaire :

| Phase | Ce qui est mesuré |
|---|---|
| **TTFB** (Time To First Byte) | Temps jusqu'au premier octet de réponse — reflète le traitement serveur |
| **Transfert** | Temps de téléchargement du corps — reflète la taille et la bande passante |

### Monitoring continu (`--interval`)

```bash
ltiprobe --interval 60        # relancer toutes les 60 secondes
ltiprobe --interval 30 --csv  # accumuler les résultats dans un seul CSV
```

Une alerte de dégradation se déclenche quand une métrique augmente de **≥ 50 %** par rapport au scan précédent.

**Correction de la coordinated omission** (Gil Tene) : en mode `--interval`, ltiprobe applique l'enregistrement corrigé HDR histogram pour éviter que les serveurs lents ne masquent les latences élevées aux percentiles P99 et P99.9.

### Comparaison avec une baseline (`--baseline`)

```bash
ltiprobe --csv                                          # sauvegarder une baseline
ltiprobe --baseline resultats_20260420_143200.csv       # comparer plus tard
ltiprobe --baseline resultats_20260420_143200.csv --csv # + rapport CSV de comparaison
```

Seuil de régression : **+10 %** sur HTTP P50, P95, P99, DNS ou TTFB.
Les baselines issues de `--interval` (plusieurs lignes par URL) sont agrégées par **médiane**.

### Export Prometheus (`--prometheus-out`)

```bash
ltiprobe --prometheus-out metrics.prom
```

Compatible avec le textfile collector de `node_exporter` et Pushgateway.
Métriques exportées : latences HTTP (P50/P95/P99/moyenne), TTFB, transfert, DNS, ICMP, TCP, TLS, ratio de stabilité, et résultats SLO (`ltiprobe_slo_ok`).

### Informations TLS avancées (`--tls-info`)

Affiche la version TLS, le cipher négocié, l'émetteur, le sujet (CN), la date d'expiration
(alerte orange < 30 jours, rouge si expiré) et la présence du header HSTS.

### Alertes webhook

```yaml
webhook:
  url: https://hooks.slack.com/services/xxx/yyy/zzz
  on: slo_violation   # slo_violation | degradation | all
```

Envoi non-bloquant (thread daemon). Compatible Slack, Teams, PagerDuty, Discord et tout endpoint HTTP.

### Jitter et packet loss

- **Jitter** : écart-type des RTT — mesure la consistance de la latence (ICMP, TCP, TLS)
- **Packet loss** : % de paquets perdus — affiché en vert (0%) ou orange (> 0%) — ICMP uniquement

### Scoring Standards (ITU-T G.107)

Quand les données ICMP sont disponibles, ltiprobe affiche une section **Scoring Standards**
appliquant le modèle E de l'ITU-T (G.107) pour estimer la qualité vocale et temps-réel.

| MOS | Qualité | Ressenti |
|---|---|---|
| ≥ 4.3 | Excellente | Comme en face-à-face |
| ≥ 4.0 | Bonne | Imperceptible |
| ≥ 3.6 | Acceptable | Tolérable |
| ≥ 3.1 | Médiocre | Effort notable |
| < 3.1 | Mauvaise | Incompréhension |

Utilisez `mos_min` dans votre SLO pour imposer un seuil de qualité minimum.

### Licence

MIT
