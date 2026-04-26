# ping-tool

Mesure les temps de réponse HTTP et DNS de sites web depuis le Terminal.
Affiche une distribution complète des latences (P50 à P99.9) avec vérification des SLOs.

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

# Aide
ping-tool --help
```

## Exemple de sortie

```
https://google.com
  HTTP  distribution (10 mesures)
    moyenne :  45.3 ms   min: 28.1   max: 145.2
    p50     :  38.0 ms  [SLO <=200ms  OK]
    p75     :  45.0 ms
    p90     :  62.0 ms
    p95     :  89.0 ms  [SLO <=400ms  OK]
    p99     : 145.0 ms
    p99.9   : 145.0 ms
  Stabilite : stable       (p99/p50 = 3.8x)
  DNS   -> moyenne: 8.2 ms  min: 6.1  max: 11.4  [SLO <=50ms  OK]
  SLO   -> tous les objectifs sont respectes
```

## Configuration

Créez un fichier `ping-tool.yaml` à la racine de votre projet pour définir les sites et leurs SLOs :

```yaml
nb_mesures: 10
timeout: 10

sites:
  - url: https://google.com
    slo:
      http_p50_ms: 200   # latence médiane max acceptable
      http_p95_ms: 400   # latence P95 max acceptable
      dns_ms: 50         # latence DNS moyenne max acceptable

  - url: https://github.com
    slo:
      http_p50_ms: 300
      http_p95_ms: 600

  - url: https://apple.com
    # aucun SLO — mesure sans vérification
```

Si le fichier est absent, ping-tool démarre avec des sites et des valeurs par défaut.

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

## Indicateur de stabilité

ping-tool calcule le ratio P99/P50 pour évaluer la régularité de la latence :

| Ratio | Interprétation |
|---|---|
| < 2x | Très stable — tous les utilisateurs ont une expérience similaire |
| 2x – 5x | Stable — quelques variations acceptables |
| 5x – 10x | Variable — pics de latence notables |
| > 10x | Instable — certains utilisateurs subissent des latences très élevées |

## Export CSV

Avec `--csv`, ping-tool génère un fichier horodaté contenant les colonnes
`moyenne`, `min`, `max`, `p50`, `p75`, `p90`, `p95`, `p99`, `p999`, `dns_moyenne` et `hdr_encode`
(histogramme compressé rejouable avec la bibliothèque [HdrHistogram](https://github.com/HdrHistogram/HdrHistogram_py)).

## Licence

MIT
