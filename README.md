# ping-tool

Mesure les temps de réponse HTTP, DNS, ICMP, TCP et TLS de sites web depuis le Terminal.
Affiche une distribution complète des latences (P50 à P99.9) avec vérification des SLOs et détection CDN/cache.

[![PyPI version](https://badge.fury.io/py/ping-tool-bglatence.svg)](https://pypi.org/project/ping-tool-bglatence/)

## Installation

```bash
pip install ping-tool-bglatence
```

## Utilisation

```bash
# Sites définis dans ping-tool.yaml (par défaut)
ping-tool

# Sites personnalisés en argument
ping-tool https://apple.com https://amazon.com

# Nombre de mesures par site
ping-tool -n 20

# Sauvegarder les résultats en CSV
ping-tool --csv

# Afficher le nombre de hops réseau (traceroute)
ping-tool --traceroute

# Afficher le nombre de hops réseau (traceroute)
ping-tool --traceroute

# Utiliser un fichier de configuration alternatif
ping-tool --config-file staging.yaml

# Aide
ping-tool --help
```

## Exemple de sortie

```
Mesure des temps de réponse (10 essais)...

https://google.com
  HTTP  distribution (10 mesures)
    moyenne :  45.3 ms   min: 28.1   max: 145.2
    p50     :  38.0 ms  [SLO <=100ms  OK]
    p75     :  45.0 ms
    p90     :  62.0 ms
    p95     :  89.0 ms  [SLO <=400ms  OK]
    p99     : 145.0 ms
    p99.9   : 145.0 ms
  Stabilité : stable       (p99/p50 = 3.8x)
  DNS   -> moyenne: 8.2 ms  min: 6.1  max: 11.4  [SLO <=50ms  OK]
  SLO   -> tous les objectifs sont respectés

  Réseau -> 14 hops  bon        (≤ 25)  (3 masqués (* * *))

  --- Comparaison protocoles (connexion froide) ---
  ICMP  (réseau)          :  12.3 ms  min: 11.1  max: 13.5  (10 paquets)
  TCP   (port 443)        :  18.7 ms  min: 17.2  max: 21.0  (+6.4 ms)
  TLS   (handshake, ×1)   :  31.2 ms  min: 28.4  max: 35.1  (+12.5 ms)
  HTTP  (p50, froid)      :  38.0 ms  (+6.8 ms)
  HTTP  (p50, keep-alive) :  19.3 ms  ← sans TCP/TLS

  ── Cache / CDN ──────────────────────────────────────
  Cache  →  HIT  Cloudflare  PoP: YYZ  Age: 42s

  ── Validation HTTP ──────────────────────────────────
  status_code     200                           →  200               ✓ OK
  body_contains   "google"                      →  trouvé            ✓ OK

  ── Analyse SLO ─────────────────────────────────────
  http_p50_ms        38.0 ms  <=  300 ms        ✓ OK
  http_p95_ms        89.0 ms  <=  400 ms        ✓ OK
  dns_ms              8.2 ms  <=   50 ms        ✓ OK
  ────────────────────────────────────────────────────
  Bilan : 3/3 objectifs respectés
```

## Configuration

Créez un fichier `ping-tool.yaml` à la racine de votre projet :

```yaml
nb_mesures: 10
timeout: 10
langue: FR        # FR ou EN

sites:
  - url: https://google.com
    slo:
      http_p50_ms: 100   # latence médiane max acceptable
      http_p95_ms: 400   # latence P95 max acceptable
      dns_ms: 50         # latence DNS moyenne max acceptable

  - url: https://github.com
    slo:
      http_p50_ms: 300
      http_p95_ms: 600

  - url: https://apple.com
    # aucun SLO — mesure sans vérification
```

Si le fichier est absent, ping-tool démarre avec des sites et valeurs par défaut.

### Options de configuration complètes

```yaml
nb_mesures: 10          # nombre de mesures par site
timeout: 10             # timeout HTTP en secondes
langue: FR              # FR (défaut) ou EN

sites:
  - url: https://api.exemple.com/health
    slo:
      http_p50_ms: 200      # latence HTTP médiane max
      http_p95_ms: 400      # latence HTTP P95 max
      dns_ms: 50            # latence DNS moyenne max
      tls_ms: 80            # handshake TLS max
      icmp_ms: 30           # latence réseau (ICMP) max
      tcp_ms: 40            # handshake TCP max
      http_chaud_ms: 150    # HTTP keep-alive (sans TCP/TLS) max
      stabilite_ratio: 5    # ratio P99/P50 max
      nb_hops_max: 25       # nombre de hops réseau max (--traceroute)
    assert:
      status_code: 200              # code HTTP attendu
      body_contains: "ok"           # chaîne attendue dans le body
      header: "Content-Type: application/json"  # header obligatoire
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
| `icmp_ms` | Latence réseau ICMP moyenne |
| `tcp_ms` | Durée du handshake TCP |
| `http_chaud_ms` | HTTP estimé keep-alive (sans TCP/TLS) |
| `stabilite_ratio` | Ratio P99/P50 (ex: `5` signifie P99 ≤ 5× P50) |
| `nb_hops_max` | Nombre de hops réseau max (requiert `--traceroute`) |

### Validation de la réponse HTTP (`assert`)

Chaque site peut déclarer des assertions vérifiées après la mesure :

| Clé | Description |
|---|---|
| `status_code` | Code HTTP attendu (ex: `200`) |
| `body_contains` | Chaîne attendue dans les premiers 4 Ko du body |
| `header` | `"Clé: Valeur"` (valeur partielle) ou `"Clé"` (présence) |

## Comparaison des couches protocolaires

Pour chaque site, ping-tool mesure les quatre couches en parallèle et affiche les deltas :

| Couche | Ce qui est mesuré |
|---|---|
| ICMP | Latence réseau pure (ping) |
| TCP | Surcoût du handshake TCP (connect) |
| TLS | Surcoût du handshake SSL/TLS — **payé une seule fois** par connexion |
| HTTP froid | Requête complète (nouvelle connexion : inclut TCP + TLS) |
| HTTP keep-alive | Estimation sans TCP/TLS — représente le traitement serveur + transfert |

> **Note :** La comparaison est faite sur une *connexion froide*. En production avec HTTP keep-alive ou HTTP/2, seul le coût HTTP keep-alive s'applique à chaque requête.

## Indicateur de stabilité

ping-tool calcule le ratio P99/P50 pour évaluer la régularité de la latence :

| Ratio | Interprétation |
|---|---|
| < 2x | Très stable — tous les utilisateurs ont une expérience similaire |
| 2x – 5x | Stable — quelques variations acceptables |
| 5x – 10x | Variable — pics de latence notables |
| > 10x | Instable — certains utilisateurs subissent des latences très élevées |

## Indicateur de hops réseau (`--traceroute`)

Le flag `--traceroute` affiche le nombre de hops entre vous et le serveur :

| Hops | Indicateur |
|---|---|
| ≤ 15 | Excellent — route très directe |
| ≤ 25 | Bon — routage normal |
| ≤ 35 | Élevé — route longue (typiquement intercontinental) |
| > 35 | Critique — route sous-optimale ou problème de routage |

Les hops masqués (`* * *`) sont comptabilisés mais signalés séparément.

## Détection CDN et statut cache

Pour chaque site, ping-tool envoie automatiquement une requête HEAD en parallèle et lit les headers de réponse pour détecter si la réponse provient d'un cache CDN ou du serveur d'origine.

| CDN détecté | Header analysé |
|---|---|
| Cloudflare | `CF-Ray` |
| CloudFront (AWS) | `X-Amz-Cf-Pop` |
| Fastly | `X-Served-By` |
| Akamai | `X-Check-Cacheable` |
| Varnish | `Via` |

Le statut cache (`HIT` ou `MISS`), le point de présence réseau (PoP, ex: `YYZ` = Toronto) et l'âge de l'entrée cache sont affichés dans la section **Cache / CDN**.

Cette information explique souvent une latence anormalement basse (cache HIT proche) ou haute (requête remontée à l'origine).

## Profils multi-environnements (`--config-file`)

Créez un fichier de configuration par environnement et sélectionnez-le à l'exécution :

```bash
ping-tool --config-file prod.yaml
ping-tool --config-file staging.yaml
```

## Support multilingue

Définissez `langue: EN` dans `ping-tool.yaml` pour afficher les résultats en anglais.
Valeurs acceptées : `FR` (défaut) et `EN`.

## Export CSV

Avec `--csv`, ping-tool génère un fichier horodaté contenant les colonnes
`moyenne`, `min`, `max`, `p50`, `p75`, `p90`, `p95`, `p99`, `p999`, `dns_moyenne` et `hdr_encode`
(histogramme compressé rejouable avec la bibliothèque [HdrHistogram](https://github.com/HdrHistogram/HdrHistogram_py)).

## Licence

MIT
