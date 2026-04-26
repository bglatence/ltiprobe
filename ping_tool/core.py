# -*- coding: utf-8 -*-
import urllib.request
import urllib.error
import socket
import time
import csv
from datetime import datetime
from hdrh.histogram import HdrHistogram
from . import config

# Plage 1µs–60s, 3 chiffres significatifs
_HDR_MIN_US = 1
_HDR_MAX_US = 60_000_000

def calculer_percentiles(mesures_ms):
    """Calcule p50/p95/p99 en ms à partir d'une liste de mesures (float ms)."""
    hist = HdrHistogram(_HDR_MIN_US, _HDR_MAX_US, 3)
    for ms in mesures_ms:
        hist.record_value(max(1, int(ms * 1000)))
    return {
        "p50": round(hist.get_value_at_percentile(50)  / 1000, 2),
        "p95": round(hist.get_value_at_percentile(95)  / 1000, 2),
        "p99": round(hist.get_value_at_percentile(99)  / 1000, 2),
    }

def mesurer_dns(hostname):
    """Mesure uniquement le temps de resolution DNS. Retourne ms ou None."""
    try:
        debut = time.perf_counter()
        socket.getaddrinfo(hostname, None)
        fin = time.perf_counter()
        return round((fin - debut) * 1000, 2)
    except socket.gaierror:
        return None

def extraire_hostname(url):
    """Extrait le hostname d'une URL. Ex: https://google.com -> google.com"""
    url = url.replace("https://", "").replace("http://", "")
    return url.split("/")[0]

def mesurer_site(url, nb_mesures=None, timeout=None):
    """Mesure le temps de reponse HTTP et DNS d'un site. Retourne un dict."""
    nb = nb_mesures or config.NB_MESURES
    to = timeout or config.TIMEOUT
    mesures_http = []
    mesures_dns = []

    hostname = extraire_hostname(url)

    for _ in range(nb):
        # Mesure DNS
        dns_ms = mesurer_dns(hostname)
        if dns_ms is None:
            return {
                "url": url,
                "erreur": True,
                "type_erreur": "dns",
                "message": "Impossible de resoudre l'adresse du site : " + url
            }
        mesures_dns.append(dns_ms)

        # Mesure HTTP
        debut = time.perf_counter()
        try:
            urllib.request.urlopen(url, timeout=to)
            ms = round((time.perf_counter() - debut) * 1000, 2)
            mesures_http.append(ms)

        except urllib.error.URLError as e:
            raison = str(e.reason) if hasattr(e, 'reason') else str(e)
            if isinstance(e.reason, socket.timeout):
                return {
                    "url": url,
                    "erreur": True,
                    "type_erreur": "timeout",
                    "message": "Delai depasse pour : " + url
                }
            else:
                return {
                    "url": url,
                    "erreur": True,
                    "type_erreur": "http",
                    "message": "Erreur reseau : " + raison
                }
        except Exception as e:
            return {
                "url": url,
                "erreur": True,
                "type_erreur": "inconnu",
                "message": "Erreur inconnue : " + str(e)
            }

    percentiles = calculer_percentiles(mesures_http)
    return {
        "url": url,
        "erreur": False,
        "type_erreur": None,
        "message": None,
        # HTTP
        "moyenne": round(sum(mesures_http) / len(mesures_http), 2),
        "min": min(mesures_http),
        "max": max(mesures_http),
        "mesures": mesures_http,
        # Percentiles HTTP
        "p50": percentiles["p50"],
        "p95": percentiles["p95"],
        "p99": percentiles["p99"],
        # DNS
        "dns_moyenne": round(sum(mesures_dns) / len(mesures_dns), 2),
        "dns_min": min(mesures_dns),
        "dns_max": max(mesures_dns),
    }

def sauvegarder_csv(resultats, fichier=None):
    """Sauvegarde une liste de resultats dans un CSV."""
    nom = fichier or "resultats_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
    with open(nom, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "url", "moyenne", "min", "max",
            "dns_moyenne", "dns_min", "dns_max"
        ])
        writer.writeheader()
        for r in resultats:
            if not r["erreur"]:
                writer.writerow({
                    "url":         r.get("url"),
                    "moyenne":     r.get("moyenne"),
                    "min":         r.get("min"),
                    "max":         r.get("max"),
                    "dns_moyenne": r.get("dns_moyenne"),
                    "dns_min":     r.get("dns_min"),
                    "dns_max":     r.get("dns_max"),
                })
    return nom