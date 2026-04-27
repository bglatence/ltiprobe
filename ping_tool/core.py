# -*- coding: utf-8 -*-
import urllib.request
import urllib.error
import socket
import ssl
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
    "http_p50_ms":     "p50",
    "http_p75_ms":     "p75",
    "http_p90_ms":     "p90",
    "http_p95_ms":     "p95",
    "http_p99_ms":     "p99",
    "http_p999_ms":    "p999",
    "dns_ms":          "dns_moyenne",
    "stabilite_ratio": "stabilite_ratio",
    "icmp_ms":         "icmp_ms",
    "tcp_ms":          "tcp_ms",
    "tls_ms":          "tls_ms",
    "http_chaud_ms":   "http_chaud_ms",
    "nb_hops_max":     "nb_hops",
}

# Unité d'affichage par clé SLO (défaut : "ms")
SLO_UNITES: dict[str, str] = {
    "stabilite_ratio": "x",
    "nb_hops_max":     "hops",
}

def verifier_assertions(url, asserts, timeout=10):
    """Effectue une requête et vérifie les assertions déclarées dans le YAML.

    Clés supportées dans asserts :
      - status_code    : int — code HTTP attendu (ex: 200)
      - body_contains  : str — chaîne attendue dans les premiers 4 Ko du body
      - header         : str — "Clé: Valeur" ou juste "Clé" (présence)

    Retourne {clé: {attendu, recu, ok}} ou {"_erreur": message} si la requête échoue.
    """
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url), timeout=timeout
        ) as resp:
            status  = resp.status
            headers = resp.headers
            body    = resp.read(4096).decode("utf-8", errors="replace")
    except Exception as e:
        return {"_erreur": str(e)}

    checks: dict[str, dict] = {}

    if "status_code" in asserts:
        attendu = int(asserts["status_code"])
        checks["status_code"] = {
            "attendu": str(attendu),
            "recu":    str(status),
            "ok":      status == attendu,
        }

    if "body_contains" in asserts:
        terme  = str(asserts["body_contains"])
        trouve = terme in body
        checks["body_contains"] = {
            "attendu": f'"{terme}"',
            "recu":    "trouvé" if trouve else "absent",
            "ok":      trouve,
        }

    if "header" in asserts:
        h = str(asserts["header"])
        if ":" in h:
            cle, val = h.split(":", 1)
            cle = cle.strip()
            val = val.strip()
            recu = headers.get(cle, "")
            ok   = val.lower() in recu.lower()
        else:
            cle  = h.strip()
            recu = headers.get(cle, "")
            ok   = bool(recu)
        checks["header:" + cle] = {
            "attendu": h,
            "recu":    recu if recu else "absent",
            "ok":      ok,
        }

    return checks

_CDN_SIGNATURES = [
    # (nom_cdn, header_detecteur, lambda headers -> True si match)
    ("Cloudflare",  "CF-Ray",          lambda h: bool(h.get("CF-Ray"))),
    ("CloudFront",  "X-Amz-Cf-Pop",   lambda h: bool(h.get("X-Amz-Cf-Pop"))),
    ("Fastly",      "X-Served-By",     lambda h: "cache" in (h.get("X-Served-By") or "").lower()),
    ("Akamai",      "X-Check-Cacheable", lambda h: bool(h.get("X-Check-Cacheable"))),
    ("Varnish",     "Via",             lambda h: "varnish" in (h.get("Via") or "").lower()),
]

def detecter_cdn(url, timeout=10):
    """Effectue une requête HEAD et lit les headers pour détecter CDN/cache.

    Retourne un dict :
      cdn       : str | None   — nom du CDN détecté (ex: "Cloudflare")
      cache     : str | None   — statut cache : "HIT", "MISS" ou None
      age_s     : int | None   — âge du cache en secondes (header Age)
      pop       : str | None   — point de présence CDN (ex: "YUL" de CF-Ray)
      via       : str | None   — valeur brute du header Via
    Retourne None si la requête échoue.
    """
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "Mozilla/5.0 (compatible; ping-tool)")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            headers = resp.headers
    except Exception:
        return None

    cdn_nom = None
    for nom, _, fn in _CDN_SIGNATURES:
        if fn(headers):
            cdn_nom = nom
            break

    # Cache status
    cache = None
    for hdr in ("X-Cache", "CF-Cache-Status", "X-Cache-Status"):
        val = headers.get(hdr, "")
        if val:
            upper = val.upper()
            if "HIT" in upper:
                cache = "HIT"
            elif "MISS" in upper:
                cache = "MISS"
            break

    # PoP depuis CF-Ray : "abc123-YUL" → "YUL"
    pop = None
    cf_ray = headers.get("CF-Ray", "")
    if cf_ray and "-" in cf_ray:
        pop = cf_ray.split("-")[-1]
    if not pop:
        pop = headers.get("X-Amz-Cf-Pop") or headers.get("X-Served-By") or None
        if pop and len(pop) > 15:
            pop = None

    age_s = None
    age_raw = headers.get("Age", "")
    if age_raw.isdigit():
        age_s = int(age_raw)

    return {
        "cdn":   cdn_nom,
        "cache": cache,
        "age_s": age_s,
        "pop":   pop,
        "via":   headers.get("Via"),
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

def mesurer_tcp(hostname, nb_mesures=5, timeout=10):
    """Mesure la latence du handshake TCP (connect) vers hostname.

    Détecte le port automatiquement : 443 pour https, 80 sinon.
    Retourne un dict {moyenne, min, max, p50, nb} en ms, ou None si échec.
    """
    port = 443 if not hostname.startswith("http://") else 80
    hostname = hostname.replace("https://", "").replace("http://", "").split("/")[0]
    rtts = []
    hist = creer_histogramme()
    for _ in range(nb_mesures):
        try:
            debut = time.perf_counter()
            sock = socket.create_connection((hostname, port), timeout=timeout)
            ms = round((time.perf_counter() - debut) * 1000, 2)
            sock.close()
            rtts.append(ms)
            hdr_enregistrer(hist, ms)
        except Exception:
            pass
    if not rtts:
        return None
    return {
        "moyenne": round(sum(rtts) / len(rtts), 2),
        "min":     round(min(rtts), 2),
        "max":     round(max(rtts), 2),
        "p50":     round(hist.get_value_at_percentile(50) / 1000, 2),
        "nb":      len(rtts),
        "port":    port,
    }

def mesurer_traceroute(hostname, max_hops=30):
    """Compte les hops jusqu'à destination via traceroute système.

    Utilise -q 1 -w 1 pour minimiser le temps d'attente.
    Retourne {nb_hops, nb_repondus, nb_masques, destination_atteinte} ou None.
    """
    import platform
    hostname = hostname.replace("https://", "").replace("http://", "").split("/")[0]
    if platform.system() == "Windows":
        cmd = ["tracert", "-d", "-h", str(max_hops), hostname]
    else:
        cmd = ["traceroute", "-n", "-q", "1", "-w", "1", "-m", str(max_hops), hostname]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=max_hops * 4
        )
        hops = []
        for line in result.stdout.splitlines():
            m = re.match(r"^\s*(\d+)\s+", line)
            if not m:
                continue
            hop_num = int(m.group(1))
            repond = bool(re.search(r"\d+\.?\d*\s*ms", line))
            hops.append({"hop": hop_num, "repond": repond})
        if not hops:
            return None
        nb_total = hops[-1]["hop"]
        nb_repondus = sum(1 for h in hops if h["repond"])
        return {
            "nb_hops":            nb_total,
            "nb_repondus":        nb_repondus,
            "nb_masques":         nb_total - nb_repondus,
            "destination_atteinte": nb_total < max_hops,
        }
    except Exception:
        return None

def mesurer_tls(hostname, nb_mesures=5, timeout=10):
    """Mesure la latence du handshake TLS seul (après TCP connect).

    Retourne un dict {moyenne, min, max, p50, nb} en ms,
    ou None si le site n'est pas HTTPS ou si TLS échoue.
    """
    hostname = hostname.replace("https://", "").replace("http://", "").split("/")[0]
    ctx = ssl.create_default_context()
    rtts = []
    hist = creer_histogramme()
    for _ in range(nb_mesures):
        try:
            sock = socket.create_connection((hostname, 443), timeout=timeout)
            debut = time.perf_counter()
            tls_sock = ctx.wrap_socket(sock, server_hostname=hostname)
            ms = round((time.perf_counter() - debut) * 1000, 2)
            tls_sock.close()
            rtts.append(ms)
            hdr_enregistrer(hist, ms)
        except Exception:
            pass
    if not rtts:
        return None
    return {
        "moyenne": round(sum(rtts) / len(rtts), 2),
        "min":     round(min(rtts), 2),
        "max":     round(max(rtts), 2),
        "p50":     round(hist.get_value_at_percentile(50) / 1000, 2),
        "nb":      len(rtts),
    }

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
