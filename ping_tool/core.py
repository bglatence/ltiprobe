# -*- coding: utf-8 -*-
import urllib.request
import urllib.error
import socket
import subprocess
import re
import time
import csv
from datetime import datetime
from hdrh.histogram import HdrHistogram
from . import config

# 1µs → 60s, 3 chiffres significatifs
_HDR_MIN_US = 1
_HDR_MAX_US = 60_000_000

def creer_histogramme():
    return HdrHistogram(_HDR_MIN_US, _HDR_MAX_US, 3)

def hdr_enregistrer(hist, ms):
    hist.record_value(max(1, int(ms * 1000)))

def hdr_stats(hist):
    """Extrait les statistiques clés d'un histogramme en ms."""
    return {
        "moyenne": round(hist.get_mean_value()              / 1000, 2),
        "min":     round(hist.get_min_value()               / 1000, 2),
        "max":     round(hist.get_max_value()               / 1000, 2),
        "p50":     round(hist.get_value_at_percentile(50)   / 1000, 2),
        "p75":     round(hist.get_value_at_percentile(75)   / 1000, 2),
        "p90":     round(hist.get_value_at_percentile(90)   / 1000, 2),
        "p95":     round(hist.get_value_at_percentile(95)   / 1000, 2),
        "p99":     round(hist.get_value_at_percentile(99)   / 1000, 2),
        "p999":    round(hist.get_value_at_percentile(99.9) / 1000, 2),
        "hdr_encode": hist.encode(),
    }

# Correspondance clé SLO → clé dans le dict résultat
_SLO_VERS_RESULTAT = {
    "http_p50_ms":  "p50",
    "http_p75_ms":  "p75",
    "http_p90_ms":  "p90",
    "http_p95_ms":  "p95",
    "http_p99_ms":  "p99",
    "http_p999_ms": "p999",
    "dns_ms":       "dns_moyenne",
}

def verifier_slo(resultat, slo):
    """Compare un résultat mesuré contre un dict SLO.

    Retourne un dict {cle_slo: {seuil, valeur, ok}} pour chaque clé du SLO.
    """
    checks = {}
    for cle_slo, seuil in slo.items():
        cle_res = _SLO_VERS_RESULTAT.get(cle_slo)
        if cle_res is None:
            continue
        valeur = resultat.get(cle_res)
        if valeur is None:
            continue
        checks[cle_slo] = {
            "seuil":  seuil,
            "valeur": valeur,
            "ok":     valeur <= seuil,
        }
    return checks

def mesurer_icmp(hostname, nb_mesures=5):
    """Mesure la latence ICMP via la commande ping système.

    Retourne un dict {moyenne, min, max, p50, nb} en ms,
    ou None si ICMP est bloqué ou indisponible.
    """
    try:
        result = subprocess.run(
            ["ping", "-c", str(nb_mesures), hostname],
            capture_output=True, text=True, timeout=nb_mesures * 3 + 5
        )
        rtts = [
            float(m.group(1))
            for line in result.stdout.splitlines()
            for m in [re.search(r"time[=<](\d+\.?\d*)\s*ms", line)]
            if m
        ]
        if not rtts:
            return None
        hist = creer_histogramme()
        for rtt in rtts:
            hdr_enregistrer(hist, rtt)
        return {
            "moyenne": round(sum(rtts) / len(rtts), 2),
            "min":     round(min(rtts), 2),
            "max":     round(max(rtts), 2),
            "p50":     round(hist.get_value_at_percentile(50) / 1000, 2),
            "nb":      len(rtts),
        }
    except Exception:
        return None

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
    hist_http = creer_histogramme()
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

        # Mesure HTTP — enregistrement direct dans l'histogramme
        debut = time.perf_counter()
        try:
            urllib.request.urlopen(url, timeout=to)
            ms = round((time.perf_counter() - debut) * 1000, 2)
            hdr_enregistrer(hist_http, ms)

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

    stats = hdr_stats(hist_http)
    return {
        "url": url,
        "erreur": False,
        "type_erreur": None,
        "message": None,
        # HTTP
        **stats,
        # DNS
        "dns_moyenne": round(sum(mesures_dns) / len(mesures_dns), 2),
        "dns_min":     min(mesures_dns),
        "dns_max":     max(mesures_dns),
    }

def sauvegarder_csv(resultats, fichier=None):
    """Sauvegarde une liste de resultats dans un CSV."""
    nom = fichier or "resultats_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
    with open(nom, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "url", "moyenne", "min", "max",
            "p50", "p75", "p90", "p95", "p99", "p999",
            "dns_moyenne", "dns_min", "dns_max",
            "hdr_encode",
        ])
        writer.writeheader()
        for r in resultats:
            if not r["erreur"]:
                writer.writerow({
                    "url":         r.get("url"),
                    "moyenne":     r.get("moyenne"),
                    "min":         r.get("min"),
                    "max":         r.get("max"),
                    "p50":         r.get("p50"),
                    "p75":         r.get("p75"),
                    "p90":         r.get("p90"),
                    "p95":         r.get("p95"),
                    "p99":         r.get("p99"),
                    "p999":        r.get("p999"),
                    "dns_moyenne": r.get("dns_moyenne"),
                    "dns_min":     r.get("dns_min"),
                    "dns_max":     r.get("dns_max"),
                    "hdr_encode":  r.get("hdr_encode"),
                })
    return nom
