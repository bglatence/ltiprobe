# -*- coding: utf-8 -*-
import urllib.request
import urllib.error
import socket
import ssl
import ipaddress
import subprocess
import re
import time
import csv
import math
from datetime import datetime
from hdrh.histogram import HdrHistogram
from . import config


def est_adresse_ip(hostname: str) -> bool:
    """Retourne True si hostname est une adresse IPv4 ou IPv6."""
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return False

def verifier_ip_joignable(hostname, port, timeout=3):
    """Vérifie rapidement qu'une adresse IP est joignable via TCP.

    Retourne (True, None) si joignable, (False, message) sinon.
    Utilisé uniquement pour les adresses IP directes avant les mesures.
    """
    try:
        sock = socket.create_connection((hostname, port), timeout=timeout)
        sock.close()
        return True, None
    except socket.timeout:
        return False, f"{hostname}:{port} — délai dépassé (hôte non joignable)"
    except ConnectionRefusedError:
        return False, f"{hostname}:{port} — connexion refusée (port fermé)"
    except OSError as e:
        return False, f"{hostname}:{port} — {e.strerror}"

# 1µs → 60s, 3 chiffres significatifs
_HDR_MIN_US = 1
_HDR_MAX_US = 60_000_000

def creer_histogramme():
    return HdrHistogram(_HDR_MIN_US, _HDR_MAX_US, 3)

def hdr_enregistrer(hist, ms, intervalle_us=None):
    """Enregistre une mesure en ms dans l'histogramme.

    Si intervalle_us est fourni, applique la correction coordinated omission
    (Gil Tene) via record_corrected_value() — à utiliser en mode --interval.
    """
    valeur_us = max(1, int(ms * 1000))
    if intervalle_us:
        hist.record_corrected_value(valeur_us, intervalle_us)
    else:
        hist.record_value(valeur_us)

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

def _jitter(valeurs):
    """Écart-type des RTT (jitter réseau). Retourne None si moins de 2 valeurs."""
    n = len(valeurs)
    if n < 2:
        return None
    moy = sum(valeurs) / n
    return round(math.sqrt(sum((x - moy) ** 2 for x in valeurs) / n), 2)

# Correspondance clé SLO → clé dans le dict résultat
_SLO_VERS_RESULTAT = {
    "http_p50_ms":     "p50",
    "http_p75_ms":     "p75",
    "http_p90_ms":     "p90",
    "http_p95_ms":     "p95",
    "http_p99_ms":     "p99",
    "http_p999_ms":    "p999",
    "dns_ms":          "dns_moyenne",
    "stability_ratio": "stability_ratio",
    "icmp_ms":         "icmp_ms",
    "icmp_jitter_ms":  "icmp_jitter_ms",
    "icmp_loss_pct":   "icmp_loss_pct",
    "tcp_ms":          "tcp_ms",
    "tcp_jitter_ms":   "tcp_jitter_ms",
    "tls_ms":          "tls_ms",
    "mos_min":         "mos",
    "http_chaud_ms":   "http_chaud_ms",
    "nb_hops_max":     "nb_hops",
}

# Clés SLO où une valeur plus haute est meilleure (seuil = valeur minimale)
_SLO_MIN_KEYS: set[str] = {"mos_min"}

# Unité d'affichage par clé SLO (défaut : "ms")
SLO_UNITES: dict[str, str] = {
    "stability_ratio": "x",
    "nb_hops_max":     "hops",
    "mos_min":         "",
}

def lister_interfaces(interface_active=None):
    """Liste toutes les interfaces réseau physiques disponibles sur l'hôte.

    Retourne une liste de dicts {device, type, actif} ou [] si indisponible.
    'actif' est True pour l'interface utilisée pour les mesures.

    macOS : networksetup -listallhardwareports (noms lisibles officiels)
    Linux : ip link show + déduction du type depuis le préfixe du nom
    """
    import platform

    interfaces = []
    sys_name = platform.system()

    if sys_name == "Darwin":
        try:
            out = subprocess.check_output(
                ["networksetup", "-listallhardwareports"],
                text=True, timeout=5, stderr=subprocess.DEVNULL
            )
            current: dict = {}
            for line in out.splitlines():
                if line.startswith("Hardware Port:"):
                    current["type"] = line.split(":", 1)[1].strip()
                elif line.startswith("Device:"):
                    current["device"] = line.split(":", 1)[1].strip()
                elif not line.strip() and "device" in current:
                    interfaces.append({
                        "device": current["device"],
                        "type":   current.get("type", ""),
                        "actif":  current["device"] == interface_active,
                    })
                    current = {}
            if "device" in current:
                interfaces.append({
                    "device": current["device"],
                    "type":   current.get("type", ""),
                    "actif":  current["device"] == interface_active,
                })
        except Exception:
            pass

    elif sys_name == "Linux":
        _TYPE_PREFIXES = [
            ("wl",      "Wi-Fi"),
            ("wlan",    "Wi-Fi"),
            ("eth",     "Ethernet"),
            ("en",      "Ethernet"),
            ("bt",      "Bluetooth"),
            ("bnep",    "Bluetooth"),
            ("tun",     "VPN"),
            ("tap",     "VPN"),
            ("docker",  "Bridge"),
            ("br",      "Bridge"),
            ("virbr",   "Bridge"),
        ]
        try:
            out = subprocess.check_output(
                ["ip", "link", "show"], text=True, timeout=5,
                stderr=subprocess.DEVNULL
            )
            for line in out.splitlines():
                m = re.match(r"^\d+:\s+(\S+?)(?:@\S+)?:", line)
                if not m:
                    continue
                dev = m.group(1)
                if dev in ("lo",):
                    continue
                itype = next(
                    (t for p, t in _TYPE_PREFIXES if dev.startswith(p)), ""
                )
                interfaces.append({
                    "device": dev,
                    "type":   itype,
                    "actif":  dev == interface_active,
                })
        except Exception:
            pass

    return interfaces

def detecter_reseau(timeout=5):
    """Détecte l'interface réseau active, l'IP locale et l'identité publique.

    Retourne un dict :
      local_ip    : str | None        — IP locale de l'interface sortante
      interface   : str | None        — nom de l'interface (ex: "en0", "eth0")
      interfaces  : list[dict]        — toutes les interfaces disponibles
      public_ip   : str | None        — IP publique vue depuis internet
      isp         : str | None        — nom du fournisseur d'accès (FAI)
      as_info     : str | None        — numéro AS (ex: "AS812 Bell Canada")
      pays        : str | None        — pays (ex: "Canada")
      pays_code   : str | None        — code pays ISO (ex: "CA")
    """
    import platform
    import json

    result: dict = {}

    # IP locale via socket UDP sans envoi de données réelles
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2)
        sock.connect(("8.8.8.8", 80))
        result["local_ip"] = sock.getsockname()[0]
        sock.close()
    except Exception:
        result["local_ip"] = None

    # Interface réseau (platform-specific)
    result["interface"] = None
    try:
        sys_name = platform.system()
        if sys_name == "Darwin":
            out = subprocess.check_output(
                ["route", "get", "8.8.8.8"], text=True, timeout=3,
                stderr=subprocess.DEVNULL
            )
            for line in out.splitlines():
                if "interface:" in line:
                    result["interface"] = line.split(":")[-1].strip()
                    break
        elif sys_name == "Linux":
            out = subprocess.check_output(
                ["ip", "route", "get", "8.8.8.8"], text=True, timeout=3,
                stderr=subprocess.DEVNULL
            )
            m = re.search(r"\bdev\s+(\S+)", out)
            if m:
                result["interface"] = m.group(1)
    except Exception:
        pass

    # Liste de toutes les interfaces disponibles sur l'hôte
    result["interfaces"] = lister_interfaces(result.get("interface"))

    # IP publique + FAI via ip-api.com (service libre, pas d'authentification)
    result.update({"public_ip": None, "isp": None, "as_info": None,
                   "pays": None, "pays_code": None})
    try:
        fields = "status,country,countryCode,isp,as,query"
        req = urllib.request.Request(
            f"http://ip-api.com/json/?fields={fields}",
            headers={"User-Agent": "ltiprobe"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        if data.get("status") == "success":
            result["public_ip"] = data.get("query")
            result["isp"]       = data.get("isp")
            result["as_info"]   = data.get("as")
            result["pays"]      = data.get("country")
            result["pays_code"] = data.get("countryCode")
    except Exception:
        pass

    return result if any(v is not None for v in result.values()) else None

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
        req.add_header("User-Agent", "Mozilla/5.0 (compatible; ltiprobe)")
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

    Retourne un dict {cle_slo: {seuil, valeur, ok, op}} pour chaque clé du SLO.
    Les clés dans _SLO_MIN_KEYS utilisent >= (valeur plus haute = meilleure).
    """
    checks = {}
    for cle_slo, seuil in slo.items():
        cle_res = _SLO_VERS_RESULTAT.get(cle_slo)
        if cle_res is None:
            continue
        valeur = resultat.get(cle_res)
        if valeur is None:
            continue
        if cle_slo in _SLO_MIN_KEYS:
            ok = valeur >= seuil
            op = ">="
        else:
            ok = valeur <= seuil
            op = "<="
        checks[cle_slo] = {
            "seuil":  seuil,
            "valeur": valeur,
            "ok":     ok,
            "op":     op,
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
        "jitter":  _jitter(rtts),
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

def mesurer_traceroute_detail(hostname, nb_sondages=5, max_hops=30, timeout=1):
    """Analyse hop-by-hop : latence, jitter et loss par saut.

    Utilise traceroute -q nb_sondages pour obtenir plusieurs RTT par hop.
    Retourne {hops, nb_hops, destination_atteinte} ou None.
    Chaque hop : {hop, ip, moyenne, min, max, jitter, loss_pct, silencieux, atteint}.
    """
    import platform
    import statistics as _stats
    hostname = hostname.replace("https://", "").replace("http://", "").split("/")[0]
    if platform.system() == "Windows":
        return None
    cmd = ["traceroute", "-n", "-q", str(nb_sondages), "-w", str(timeout),
           "-m", str(max_hops), hostname]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=max_hops * (nb_sondages * timeout + 2)
        )
        destination_ip = None
        hops = []
        for line in result.stdout.splitlines():
            m = re.match(r"^\s*(\d+)\s+", line)
            if not m:
                dm = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)", line)
                if dm:
                    destination_ip = dm.group(1)
                continue
            hop_num = int(m.group(1))
            reste   = line[m.end():]
            ip_m    = re.search(r"(\d+\.\d+\.\d+\.\d+)", reste)
            ip      = ip_m.group(1) if ip_m else None
            rtts    = [float(v) for v in re.findall(r"(\d+\.?\d*)\s*ms", reste)]
            nb_perdus = max(0, nb_sondages - len(rtts))
            loss_pct  = round(nb_perdus / nb_sondages * 100) if nb_sondages else 0
            silencieux = len(rtts) == 0
            if rtts:
                moyenne = round(sum(rtts) / len(rtts), 2)
                mini    = round(min(rtts), 2)
                maxi    = round(max(rtts), 2)
                jitter  = round(_stats.stdev(rtts), 2) if len(rtts) > 1 else 0.0
            else:
                moyenne = mini = maxi = jitter = None
            atteint = (ip == destination_ip) if destination_ip and ip else False
            hops.append({
                "hop":        hop_num,
                "ip":         ip,
                "moyenne":    moyenne,
                "min":        mini,
                "max":        maxi,
                "jitter":     jitter,
                "loss_pct":   loss_pct,
                "silencieux": silencieux,
                "atteint":    atteint,
            })
        if not hops:
            return None
        if not any(h["atteint"] for h in hops):
            hops[-1]["atteint"] = hops[-1]["hop"] < max_hops
        return {
            "hops":                 hops,
            "nb_hops":              hops[-1]["hop"],
            "destination_atteinte": any(h["atteint"] for h in hops),
        }
    except Exception:
        return None

def mesurer_tls(hostname, nb_mesures=5, timeout=10, verify=True):
    """Mesure la latence du handshake TLS seul (après TCP connect).

    verify=False désactive la validation du certificat (utile pour les IPs).
    Retourne un dict {moyenne, min, max, p50, nb} en ms, ou None si échec.
    """
    hostname = hostname.replace("https://", "").replace("http://", "").split("/")[0]
    if verify:
        ctx = ssl.create_default_context()
    else:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
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
        "jitter":  _jitter(rtts),
    }

_SEUIL_EXPIRY_ALERTE = 30  # jours avant expiration → alerte

def inspecter_tls(hostname, timeout=10, verify=True):
    """Inspecte le certificat et la configuration TLS d'un serveur HTTPS.

    Retourne un dict :
      version     : str        — "TLSv1.3", "TLSv1.2", …
      cipher      : str        — suite chiffrée négociée
      issuer      : str        — nom de l'émetteur du certificat
      subject     : str        — CN du certificat (domaine couvert)
      expire_date : date       — date d'expiration
      jours_restants : int     — jours avant expiration (négatif si expiré)
      hsts        : str|None   — valeur brute du header Strict-Transport-Security
    Retourne None si la connexion échoue.
    """
    from datetime import date as date_type
    hostname = hostname.replace("https://", "").replace("http://", "").split("/")[0]
    if verify:
        ctx = ssl.create_default_context()
    else:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        sock = socket.create_connection((hostname, 443), timeout=timeout)
        tls_sock = ctx.wrap_socket(sock, server_hostname=hostname)
        version = tls_sock.version() or ""
        cipher_info = tls_sock.cipher() or ("", "", 0)
        cert = tls_sock.getpeercert() or {}
        tls_sock.close()
    except Exception:
        return None

    # Émetteur
    issuer_dict = dict(x[0] for x in cert.get("issuer", []))
    issuer = issuer_dict.get("organizationName") or issuer_dict.get("commonName") or "?"

    # Sujet (CN)
    subject_dict = dict(x[0] for x in cert.get("subject", []))
    subject = subject_dict.get("commonName") or "?"

    # Date d'expiration — format : "Aug 14 12:00:00 2025 GMT"
    expire_date = None
    jours_restants = None
    not_after = cert.get("notAfter", "")
    if not_after:
        try:
            expire_dt = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
            expire_date = expire_dt.date()
            jours_restants = (expire_date - date_type.today()).days
        except ValueError:
            pass

    # HSTS — requête HEAD séparée
    hsts = None
    try:
        req = urllib.request.Request(f"https://{hostname}", method="HEAD")
        req.add_header("User-Agent", "Mozilla/5.0 (compatible; ltiprobe)")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            hsts = resp.headers.get("Strict-Transport-Security")
    except Exception:
        pass

    return {
        "version":        version,
        "cipher":         cipher_info[0],
        "issuer":         issuer,
        "subject":        subject,
        "expire_date":    expire_date,
        "jours_restants": jours_restants,
        "hsts":           hsts,
    }

def mesurer_icmp(hostname, nb_mesures=5):
    """Mesure la latence ICMP via la commande ping système.

    Retourne un dict {moyenne, min, max, p50, nb, jitter, loss_pct} en ms,
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
        loss_pct = round((nb_mesures - len(rtts)) / nb_mesures * 100, 1)
        return {
            "moyenne":  round(sum(rtts) / len(rtts), 2),
            "min":      round(min(rtts), 2),
            "max":      round(max(rtts), 2),
            "p50":      round(hist.get_value_at_percentile(50) / 1000, 2),
            "nb":       len(rtts),
            "jitter":   _jitter(rtts),
            "loss_pct": loss_pct,
        }
    except Exception:
        return None

def decouvrir_path_mtu(hostname, mtu_max=1500, timeout=1):
    """Découvre le Path MTU par dichotomie de sondes ICMP avec bit DF (Don't Fragment).

    Utilise ping -D (macOS) ou ping -M do (Linux) — pas de raw socket requis.
    Payload = MTU candidat - 28 octets (en-tête IP 20 + en-tête ICMP 8).

    Retourne un dict :
      mtu       : int | None  — Path MTU découvert en octets
      sondages  : int         — nombre de sondes envoyées
      blackhole : bool        — True si même les petits paquets DF échouent
    Retourne None si ping ou la plateforme n'est pas supporté.
    """
    import platform

    hostname = hostname.replace("https://", "").replace("http://", "").split("/")[0]
    sys_name = platform.system()

    def sonder(taille_mtu):
        """Retourne True si un paquet de taille_mtu octets passe, False sinon, None si erreur."""
        payload = taille_mtu - 28
        if payload < 8:
            return False
        try:
            if sys_name == "Darwin":
                cmd = ["ping", "-D", "-s", str(payload), "-c", "1",
                       "-W", str(int(timeout * 1000)), hostname]
            elif sys_name == "Linux":
                cmd = ["ping", "-M", "do", "-s", str(payload), "-c", "1",
                       "-W", str(int(timeout)), hostname]
            else:
                return None
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout + 2
            )
            return result.returncode == 0
        except Exception:
            return None

    sondages = 0

    # Test rapide au MTU standard
    res = sonder(mtu_max)
    sondages += 1
    if res is None:
        return None
    if res:
        return {"mtu": mtu_max, "sondages": sondages, "blackhole": False}

    # Test au minimum pour détecter un blackhole PMTUD
    mtu_min = 576
    if not sonder(mtu_min):
        sondages += 1
        return {"mtu": None, "sondages": sondages, "blackhole": True}
    sondages += 1

    # Dichotomie entre mtu_min et mtu_max
    lo, hi = mtu_min, mtu_max
    mtu_trouve = mtu_min
    while hi - lo > 1:
        mid = (lo + hi) // 2
        res = sonder(mid)
        sondages += 1
        if res:
            lo = mid
            mtu_trouve = mid
        else:
            hi = mid

    return {"mtu": mtu_trouve, "sondages": sondages, "blackhole": False}

def mesurer_dns(hostname):
    """Mesure uniquement le temps de resolution DNS. Retourne ms ou None."""
    try:
        debut = time.perf_counter()
        socket.getaddrinfo(hostname, None)
        fin = time.perf_counter()
        return round((fin - debut) * 1000, 2)
    except socket.gaierror:
        return None

def mesurer_dns_ttl(hostname, timeout=5):
    """Mesure le comportement du cache DNS et lit le TTL de l'enregistrement A.

    Effectue deux résolutions :
      1. Via dnspython sans cache (toujours réseau) → latence réseau + TTL du serveur
      2. Via socket.getaddrinfo() en double appel → latence cache OS (2e appel)

    Retourne un dict {reseau_ms, cache_ms, ttl_s} ou None si les deux échouent.
    """
    import dns.resolver as _resolver

    reseau_ms = None
    ttl_s     = None
    cache_ms  = None

    # Résolution réseau directe — bypass le cache OS, toujours un aller-retour DNS
    try:
        r = _resolver.Resolver()
        r.cache = None
        debut   = time.perf_counter()
        answer  = r.resolve(hostname, "A", lifetime=timeout)
        reseau_ms = round((time.perf_counter() - debut) * 1000, 2)
        ttl_s     = answer.rrset.ttl
    except Exception:
        pass

    # Cache OS — premier appel pour peupler, second appel pour mesurer le cache
    try:
        socket.getaddrinfo(hostname, None)
        debut    = time.perf_counter()
        socket.getaddrinfo(hostname, None)
        cache_ms = round((time.perf_counter() - debut) * 1000, 2)
    except Exception:
        pass

    if reseau_ms is None and cache_ms is None:
        return None

    return {
        "reseau_ms": reseau_ms,
        "cache_ms":  cache_ms,
        "ttl_s":     ttl_s,
    }

def extraire_hostname(url):
    """Extrait le hostname d'une URL, même si le schéma est malformé (https// vs https://)."""
    if "//" in url:
        return url.split("//")[-1].split("/")[0]
    return url.split("/")[0]

def mesurer_site(url, nb_mesures=None, timeout=None, verify_tls=True):
    """Mesure le temps de reponse HTTP et DNS d'un site. Retourne un dict."""
    nb = nb_mesures or config.NB_MESURES
    to = timeout or config.TIMEOUT
    hist_http = creer_histogramme()
    mesures_dns  = []
    ttfb_mesures = []
    transfert_mesures = []

    hostname = extraire_hostname(url)
    ip_mode = est_adresse_ip(hostname)

    for _ in range(nb):
        # Mesure DNS — ignorée pour les adresses IP directes
        if not ip_mode:
            dns_ms = mesurer_dns(hostname)
            if dns_ms is None:
                return {
                    "url": url,
                    "erreur": True,
                    "type_erreur": "dns",
                    "message": "Impossible de resoudre l'adresse du site : " + url
                }
            mesures_dns.append(dns_ms)

        # Mesure HTTP — urlopen() retourne dès que les headers sont reçus ;
        # resp.read() lit le body. On chronométre les deux phases séparément.
        debut = time.perf_counter()
        try:
            if not verify_tls:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                resp = urllib.request.urlopen(url, timeout=to, context=ctx)
            else:
                resp = urllib.request.urlopen(url, timeout=to)

            ttfb_ms = round((time.perf_counter() - debut) * 1000, 2)
            t1 = time.perf_counter()
            resp.read()
            resp.close()
            transfert_ms = round((time.perf_counter() - t1) * 1000, 2)

            ms = round(ttfb_ms + transfert_ms, 2)
            hdr_enregistrer(hist_http, ms)
            ttfb_mesures.append(ttfb_ms)
            transfert_mesures.append(transfert_ms)

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
        "ip_mode": ip_mode,
        # HTTP
        **stats,
        # DNS — None si adresse IP directe
        "dns_moyenne": round(sum(mesures_dns) / len(mesures_dns), 2) if mesures_dns else None,
        "dns_min":     min(mesures_dns) if mesures_dns else None,
        "dns_max":     max(mesures_dns) if mesures_dns else None,
        # TTFB / Transfert — moyenne si nb > 1, valeur unique si nb == 1
        "ttfb_ms":      round(sum(ttfb_mesures) / len(ttfb_mesures), 2) if ttfb_mesures else None,
        "transfert_ms": round(sum(transfert_mesures) / len(transfert_mesures), 2) if transfert_mesures else None,
    }

def calculer_mos(latence_ms, jitter_ms=0.0, loss_pct=0.0):
    """Calcule le MOS selon l'ITU-T G.107 E-Model (codec G.711 comme référence).

    Entrées :
      latence_ms : float — latence moyenne aller-retour ICMP en ms
      jitter_ms  : float — jitter (StDev des RTT) en ms
      loss_pct   : float — taux de perte en % (0–100)

    Retourne un dict {r_factor, mos, qualite}.
    qualite : "excellente" | "bonne" | "acceptable" | "mediocre" | "mauvaise"
    """
    # Délai effectif : latence + estimation du jitter buffer (2× jitter)
    delay = latence_ms + (jitter_ms or 0.0) * 2.0

    # Id — dégradation due au délai (G.107 §B.3)
    h = 1 if delay > 177.3 else 0
    id_ = 0.024 * delay + 0.11 * (delay - 177.3) * h

    # Ie — dégradation due aux pertes (G.711 : Bpl = 25)
    loss = (loss_pct or 0.0) / 100.0
    ie = 7.0 + 30.0 * math.log(1.0 + 15.0 * loss) if loss > 0 else 0.0

    # R-factor (plafonné 0–100)
    r = max(0.0, min(100.0, 93.2 - id_ - ie))

    # R → MOS (G.107 §B.4)
    mos = 1.0 + 0.035 * r + r * (r - 60) * (100 - r) * 7e-6
    mos = round(max(1.0, min(4.5, mos)), 2)

    if mos >= 4.3:
        qualite = "excellente"
    elif mos >= 4.0:
        qualite = "bonne"
    elif mos >= 3.6:
        qualite = "acceptable"
    elif mos >= 3.1:
        qualite = "mediocre"
    else:
        qualite = "mauvaise"

    return {"r_factor": round(r, 1), "mos": mos, "qualite": qualite}

def envoyer_webhook(webhook_url, payload, timeout=5):
    """Envoie un payload JSON vers un endpoint HTTP POST (webhook).

    Retourne True si la requête aboutit (2xx), False en cas d'erreur.
    Conçu pour être appelé dans un thread daemon — non-bloquant pour la boucle principale.
    """
    import json
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url, data=data,
            headers={"Content-Type": "application/json", "User-Agent": "ltiprobe"}
        )
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception:
        return False

def sauvegarder_csv(resultats, fichier=None):
    """Sauvegarde une liste de resultats dans un CSV."""
    nom = fichier or "resultats_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
    with open(nom, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "url", "moyenne", "min", "max",
            "p50", "p75", "p90", "p95", "p99", "p999",
            "dns_moyenne", "dns_min", "dns_max",
            "ttfb_p50", "transfert_p50",
            "hdr_encode",
        ])
        writer.writeheader()
        for r in resultats:
            if not r["erreur"]:
                writer.writerow({
                    "url":          r.get("url"),
                    "moyenne":      r.get("moyenne"),
                    "min":          r.get("min"),
                    "max":          r.get("max"),
                    "p50":          r.get("p50"),
                    "p75":          r.get("p75"),
                    "p90":          r.get("p90"),
                    "p95":          r.get("p95"),
                    "p99":          r.get("p99"),
                    "p999":         r.get("p999"),
                    "dns_moyenne":  r.get("dns_moyenne"),
                    "dns_min":      r.get("dns_min"),
                    "dns_max":      r.get("dns_max"),
                    "ttfb_p50":     r.get("ttfb_p50"),
                    "transfert_p50": r.get("transfert_p50"),
                    "hdr_encode":   r.get("hdr_encode"),
                })
    return nom

# Seuil au-delà duquel une hausse est considérée comme une régression
_SEUIL_REGRESSION = 0.10

# Métriques comparées : (nom affiché, clé résultat, colonne CSV baseline, préfixe CSV comparaison)
_METRIQUES_BASELINE = [
    ("HTTP p50", "p50",         "p50",         "http_p50"),
    ("HTTP p95", "p95",         "p95",         "http_p95"),
    ("HTTP p99", "p99",         "p99",         "http_p99"),
    ("DNS",      "dns_moyenne", "dns_moyenne",  "dns"),
    ("TTFB p50", "ttfb_p50",   "ttfb_p50",    "ttfb_p50"),
]

def _mediane_valeurs(valeurs):
    """Médiane d'une liste de floats (None ignorés). Retourne None si vide."""
    s = sorted(v for v in valeurs if v is not None)
    if not s:
        return None
    return s[len(s) // 2]

def charger_baseline(fichier):
    """Charge un CSV de baseline et retourne {url: {colonne: valeur, 'date': str}}.

    Supporte les CSV multi-lignes par URL (issus de --interval) :
    les valeurs numériques sont agrégées par médiane, ce qui rend la baseline
    robuste aux spikes transitoires.

    La date est extraite du nom de fichier (resultats_YYYYMMDD_*.csv)
    ou de la date de modification du fichier.
    """
    import os
    try:
        nom = os.path.basename(fichier)
        tz_abbr = datetime.now().astimezone().strftime("%Z")
        m = re.search(r"(\d{8})_(\d{6})", nom)
        if m:
            dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
            date = dt.strftime("%Y-%m-%d %H:%M") + " " + tz_abbr
        else:
            dt = datetime.fromtimestamp(os.path.getmtime(fichier))
            date = dt.strftime("%Y-%m-%d %H:%M") + " " + tz_abbr

        # Regrouper toutes les lignes par URL
        rows_par_url: dict[str, list] = {}
        with open(fichier, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                url = row.get("url", "").strip()
                if url:
                    rows_par_url.setdefault(url, []).append(row)

        baseline = {}
        for url, rows in rows_par_url.items():
            entry: dict = {"date": date}
            for _, _, col, _ in _METRIQUES_BASELINE:
                valeurs = []
                for row in rows:
                    val = row.get(col, "").strip()
                    if val:
                        try:
                            valeurs.append(float(val))
                        except ValueError:
                            pass
                entry[col] = _mediane_valeurs(valeurs)
            baseline[url] = entry
        return baseline
    except FileNotFoundError:
        raise FileNotFoundError(f"Fichier baseline introuvable : {fichier}")
    except Exception as e:
        raise ValueError(f"Baseline invalide ({fichier}) : {e}")

def comparer_baseline(resultat, baseline_entry):
    """Compare un résultat avec une entrée baseline.

    Retourne une liste ordonnée de dicts :
      {nom, cle_csv, avant, apres, delta_pct, statut}
    Les métriques absentes (avant ou apres None) sont omises.
    """
    comparaisons = []
    for nom, cle_res, col_base, cle_csv in _METRIQUES_BASELINE:
        avant = baseline_entry.get(col_base)
        apres = resultat.get(cle_res)
        if avant is None or apres is None or avant <= 0:
            continue
        delta = (apres - avant) / avant
        if delta >= _SEUIL_REGRESSION:
            statut = "regression"
        elif delta < 0:
            statut = "amelioration"
        else:
            statut = "stable"
        comparaisons.append({
            "nom":       nom,
            "cle_csv":   cle_csv,
            "avant":     round(avant, 1),
            "apres":     round(apres, 1),
            "delta_pct": round(delta * 100),
            "statut":    statut,
        })
    return comparaisons

_PROMETHEUS_METRIQUES = [
    ("ltiprobe_http_p50_ms",      "p50",            "HTTP response time p50 in milliseconds"),
    ("ltiprobe_http_p95_ms",      "p95",            "HTTP response time p95 in milliseconds"),
    ("ltiprobe_http_p99_ms",      "p99",            "HTTP response time p99 in milliseconds"),
    ("ltiprobe_http_moyenne_ms",  "moyenne",        "HTTP response time mean in milliseconds"),
    ("ltiprobe_ttfb_p50_ms",      "ttfb_p50",       "Time to first byte p50 in milliseconds"),
    ("ltiprobe_transfert_p50_ms", "transfert_p50",  "Transfer time p50 in milliseconds"),
    ("ltiprobe_dns_moyenne_ms",   "dns_moyenne",    "DNS resolution time mean in milliseconds"),
    ("ltiprobe_icmp_ms",          "icmp_ms",        "ICMP round-trip time mean in milliseconds"),
    ("ltiprobe_tcp_ms",           "tcp_ms",         "TCP handshake time mean in milliseconds"),
    ("ltiprobe_tls_ms",           "tls_ms",         "TLS handshake time mean in milliseconds"),
    ("ltiprobe_stability_ratio",  "stability_ratio","Stability ratio p99/p50"),
]

def _prom_label(valeur):
    """Échappe les caractères spéciaux dans une valeur de label Prometheus."""
    return valeur.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

def sauvegarder_prometheus(resultats, fichier):
    """Exporte les métriques au format Prometheus text (compatible node_exporter/Pushgateway)."""
    lines = []

    for nom_metric, cle_res, help_text in _PROMETHEUS_METRIQUES:
        valeurs = [
            (r["url"], r[cle_res])
            for r in resultats
            if not r.get("erreur") and r.get(cle_res) is not None
        ]
        if not valeurs:
            continue
        lines.append(f"# HELP {nom_metric} {help_text}")
        lines.append(f"# TYPE {nom_metric} gauge")
        for url, val in valeurs:
            lines.append(f'{nom_metric}{{url="{_prom_label(url)}"}} {val}')

    slo_lines = []
    for r in resultats:
        if r.get("erreur"):
            continue
        for cle_slo, c in (r.get("slo_checks") or {}).items():
            val = 1.0 if c["ok"] else 0.0
            slo_lines.append(
                f'ltiprobe_slo_ok{{url="{_prom_label(r["url"])}", slo="{cle_slo}"}} {val}'
            )
    if slo_lines:
        lines.append("# HELP ltiprobe_slo_ok SLO objective met (1) or violated (0)")
        lines.append("# TYPE ltiprobe_slo_ok gauge")
        lines.extend(slo_lines)

    with open(fichier, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        if lines:
            f.write("\n")
    return fichier

def sauvegarder_csv_comparaison(resultats, fichier=None):
    """Sauvegarde un rapport de comparaison baseline (une ligne par site, format large).

    Générée uniquement quand --baseline et --csv sont combinés.
    Colonnes : url, date_baseline, puis pour chaque métrique :
      {metric}_avant, {metric}_apres, {metric}_delta_pct, {metric}_statut
    """
    nom = fichier or "comparaison_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
    fieldnames = ["url", "date_baseline"]
    for _, _, _, cle_csv in _METRIQUES_BASELINE:
        fieldnames += [
            f"{cle_csv}_avant",
            f"{cle_csv}_apres",
            f"{cle_csv}_delta_pct",
            f"{cle_csv}_statut",
        ]
    with open(nom, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in resultats:
            cmp = r.get("baseline_comparaison")
            if not cmp or r.get("erreur"):
                continue
            row: dict = {"url": r["url"], "date_baseline": cmp["date"]}
            par_cle = {c["cle_csv"]: c for c in cmp["lignes"]}
            for _, _, _, cle_csv in _METRIQUES_BASELINE:
                c = par_cle.get(cle_csv)
                if c:
                    row[f"{cle_csv}_avant"]     = c["avant"]
                    row[f"{cle_csv}_apres"]     = c["apres"]
                    row[f"{cle_csv}_delta_pct"] = c["delta_pct"]
                    row[f"{cle_csv}_statut"]    = c["statut"]
                else:
                    row[f"{cle_csv}_avant"]     = ""
                    row[f"{cle_csv}_apres"]     = ""
                    row[f"{cle_csv}_delta_pct"] = ""
                    row[f"{cle_csv}_statut"]    = ""
            writer.writerow(row)
    return nom
