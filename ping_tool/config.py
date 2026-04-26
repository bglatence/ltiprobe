# -*- coding: utf-8 -*-

# Sites a tester par defaut
# Chaque site peut definir un SLO optionnel avec les cles :
#   http_p50_ms, http_p75_ms, http_p90_ms, http_p95_ms, http_p99_ms, http_p999_ms, dns_ms
SITES_DEFAUT = [
    {
        "url": "https://google.com",
        "slo": {
            "http_p50_ms":  200,
            "http_p95_ms":  400,
            "dns_ms":        50,
        }
    },
    {
        "url": "https://github.com",
        "slo": {
            "http_p50_ms":  300,
            "http_p95_ms":  600,
            "dns_ms":        80,
        }
    },
    {
        "url": "https://youtube.com",
        "slo": {
            "http_p50_ms":  250,
            "http_p95_ms":  500,
        }
    },
    {
        "url": "https://apple.com",
    },
]

# Nombre de mesures par site
NB_MESURES = 10

# Timeout en secondes
TIMEOUT = 10

# Nom du fichier CSV de sortie (None = nom automatique)
FICHIER_CSV = None
