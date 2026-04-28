# -*- coding: utf-8 -*-
import argparse
import sys
import time
import threading
from datetime import datetime, timezone
from tqdm import tqdm
from ltiprobe import config, __version__
from ltiprobe.i18n import get_translator
from ltiprobe.core import (
    mesurer_site, sauvegarder_csv, sauvegarder_prometheus,
    creer_histogramme, hdr_enregistrer, hdr_stats,
    verifier_slo, verifier_assertions,
    mesurer_icmp, mesurer_tcp, mesurer_tls, mesurer_traceroute,
    detecter_cdn, est_adresse_ip, verifier_ip_joignable,
    charger_baseline, comparer_baseline, sauvegarder_csv_comparaison,
    SLO_UNITES,
)

# Codes ANSI — désactivés si la sortie n'est pas un terminal (fichier, CI)
def _ansi(code):
    return "\033[" + code + "m" if sys.stdout.isatty() else ""

VERT   = _ansi("92")
ORANGE = _ansi("33")
ROUGE  = _ansi("91")
RESET  = _ansi("0")

# Traducteur — initialisé dans main() après chargement du fichier de config
t = get_translator(config.LANGUE)

# Seuil de détection de dégradation : +50% par rapport à l'itération précédente
SEUIL_DEGRADATION = 0.50

def _heure_scan():
    """Retourne l'heure locale avec timezone et l'équivalent UTC."""
    local = datetime.now().astimezone()
    utc   = datetime.now(timezone.utc)
    return f"{local.strftime('%H:%M')} {local.strftime('%Z')} / {utc.strftime('%H:%M')} UTC"

def _heure_locale():
    """Retourne l'heure locale avec abréviation de timezone (pour les alertes)."""
    local = datetime.now().astimezone()
    return f"{local.strftime('%H:%M')} {local.strftime('%Z')}"

_NOMS_METRIQUES = {
    "p50":         "p50",
    "p95":         "p95",
    "p99":         "p99",
    "dns_moyenne": "dns",
    "icmp_ms":     "icmp",
}

def parse_arguments():
    # Pré-parse pour récupérer --config-file avant de charger la config complète
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config-file", default=None)
    pre_args, _ = pre.parse_known_args()

    cfg = config.charger(pre_args.config_file)

    parser = argparse.ArgumentParser(
        prog="ltiprobe",
        description="Mesure les temps de reponse HTTP de sites web"
    )
    parser.add_argument("--version", action="version", version=f"ltiprobe {__version__}")
    parser.add_argument(
        "--config-file",
        default=None,
        metavar="FICHIER",
        help=f"Fichier de configuration YAML (defaut: {config.FICHIER_DEFAUT})"
    )
    parser.add_argument(
        "sites", nargs="*",
        help="Sites a tester (ex: https://google.com https://github.com)"
    )
    parser.add_argument(
        "-n", "--nombre", type=int, default=cfg["nb_mesures"],
        help="Nombre de mesures par site (defaut: %(default)s)"
    )
    parser.add_argument("--csv", action="store_true",
        help="Sauvegarder les resultats dans un fichier CSV")
    parser.add_argument(
        "--timeout", type=int, default=cfg["timeout"],
        help="Timeout en secondes (defaut: %(default)s)"
    )
    parser.add_argument("--traceroute", action="store_true",
        help="Afficher le nombre de hops reseau vers chaque site")
    parser.add_argument("--no-verify-tls", action="store_true",
        help="Desactiver la validation du certificat TLS (utile pour les adresses IP)")
    parser.add_argument(
        "--interval", type=int, default=None, metavar="SECONDES",
        help="Relancer les mesures toutes les N secondes (monitoring continu)"
    )
    parser.add_argument(
        "--baseline", default=None, metavar="FICHIER",
        help="CSV de reference pour detecter les regressions de performance"
    )
    parser.add_argument(
        "--prometheus-out", default=None, metavar="FICHIER",
        help="Exporter les metriques au format Prometheus text (ex: metrics.prom)"
    )
    return parser.parse_args(), cfg

# ── Indicateurs colorés ───────────────────────────────────────────────────────

def indicateur_stabilite(p50, p99):
    if p50 <= 0:
        return "n/a"
    ratio = p99 / p50
    ratio_str = t("ratio", r=round(ratio, 1))
    if ratio < 2:
        return VERT   + t("tres_stable") + ratio_str + RESET
    if ratio < 5:
        return VERT   + t("stable")      + ratio_str + RESET
    if ratio < 10:
        return ORANGE + t("variable")    + ratio_str + RESET
    return ROUGE  + t("instable")    + ratio_str + RESET

def indicateur_hops(nb_hops):
    if nb_hops <= 15:
        return VERT   + t("hops_excellent") + RESET
    if nb_hops <= 25:
        return VERT   + t("hops_bon")       + RESET
    if nb_hops <= 35:
        return ORANGE + t("hops_eleve")     + RESET
    return ROUGE  + t("hops_critique")  + RESET

def _delta(a, b):
    if a is None or b is None or a <= 0:
        return ""
    d = round(b - a, 1)
    return ("  (+" + str(d) + " ms)") if d > 0 else ""

# ── Sections d'affichage ──────────────────────────────────────────────────────

def afficher_protocoles(icmp, tcp, tls, http_p50, site):
    port     = tcp["port"] if tcp else 443
    icmp_moy = icmp["moyenne"] if icmp else None
    tcp_moy  = tcp["moyenne"]  if tcp  else None
    tls_moy  = tls["moyenne"]  if tls  else None

    print(t("proto_titre"))
    if icmp:
        print(t("proto_icmp", v=icmp_moy, min=icmp["min"], max=icmp["max"], n=icmp["nb"]))
    else:
        print(t("proto_icmp_na"))

    if tcp:
        print(t("proto_tcp", p=port, v=tcp_moy, min=tcp["min"], max=tcp["max"])
              + _delta(icmp_moy, tcp_moy))
    else:
        print(t("proto_tcp_na", p=port))

    if tls:
        print(t("proto_tls", v=tls_moy, min=tls["min"], max=tls["max"])
              + _delta(tcp_moy if tcp_moy else icmp_moy, tls_moy))
    elif site.startswith("https://"):
        print(t("proto_tls_na"))

    if http_p50:
        prev = tls_moy or tcp_moy or icmp_moy
        print(t("proto_http_froid", v=http_p50) + _delta(prev, http_p50))
        surcharge = round((tcp_moy or 0) + (tls_moy or 0), 1)
        http_chaud = round(http_p50 - surcharge, 1)
        if surcharge > 0 and http_chaud > 0:
            print(t("proto_http_chaud", v=http_chaud))

def afficher_traceroute(tr):
    if tr is None:
        print(t("traceroute_na"))
        return
    if not tr["destination_atteinte"]:
        print(t("traceroute_non_atteint", n=tr["nb_hops"]))
        return
    masques = ("  (" + str(tr["nb_masques"]) + " " + t("hops_masques") + ")") if tr["nb_masques"] else ""
    print(t("traceroute_hops", n=tr["nb_hops"])
          + "  " + indicateur_hops(tr["nb_hops"]) + masques)

def afficher_cdn(cdn_info):
    if cdn_info is None:
        print(t("cdn_erreur"))
        return
    print(t("cdn_titre"))
    cdn_nom = cdn_info.get("cdn") or t("cdn_inconnu")
    cache   = cdn_info.get("cache")
    age_s   = cdn_info.get("age_s")
    pop     = cdn_info.get("pop")

    statut = ""
    if cache == "HIT":
        statut = VERT  + t("cdn_hit")  + RESET
    elif cache == "MISS":
        statut = ORANGE + t("cdn_miss") + RESET

    parties = []
    if pop:
        parties.append(t("cdn_pop", p=pop))
    if age_s is not None:
        parties.append(t("cdn_age", s=age_s))
    suite = "  ".join(parties)

    if not cache and not cdn_info.get("cdn"):
        print(t("cdn_aucun"))
    else:
        print(t("cdn_ligne", statut=statut, cdn=cdn_nom, suite=suite))

def afficher_assertions(assert_checks):
    if not assert_checks:
        return
    print(t("assert_titre"))
    if "_erreur" in assert_checks:
        print(t("assert_erreur", msg=assert_checks["_erreur"]))
        return
    largeur = max(len(c) for c in assert_checks) + 2
    for cle, c in assert_checks.items():
        statut = (VERT + t("slo_check_ok") + RESET) if c["ok"] else (ROUGE + t("slo_check_nok") + RESET)
        print("  " + cle.ljust(largeur) + c["attendu"].ljust(30) + "→  " + c["recu"].ljust(20) + statut)

def afficher_analyse_slo(slo_checks):
    if not slo_checks:
        return
    print(t("slo_titre"))
    largeur_cle = max(len(c) for c in slo_checks) + 2
    for cle, c in slo_checks.items():
        unite  = SLO_UNITES.get(cle, "ms")
        valeur = str(c["valeur"]) + " " + unite
        seuil  = str(c["seuil"])  + " " + unite
        statut = (VERT + t("slo_check_ok") + RESET) if c["ok"] else (ROUGE + t("slo_check_nok") + RESET)
        print("  " + cle.ljust(largeur_cle) + valeur.rjust(12) + "  <=  " + seuil.ljust(12) + statut)
    print("  " + "─" * 52)
    nb_ok    = sum(1 for c in slo_checks.values() if c["ok"])
    nb_total = len(slo_checks)
    if nb_ok == nb_total:
        print(VERT  + t("slo_bilan_ok",  ok=nb_ok, total=nb_total) + RESET)
    else:
        print(ROUGE + t("slo_bilan_nok", ok=nb_ok, total=nb_total) + RESET)

def afficher_comparaison_baseline(comparaisons, date):
    if not comparaisons:
        return
    print(t("baseline_titre", date=date))
    for c in comparaisons:
        signe     = "+" if c["delta_pct"] >= 0 else ""
        delta_str = (signe + str(c["delta_pct"]) + "%").rjust(6)
        if c["statut"] == "regression":
            statut_str = ORANGE + t("baseline_regression") + RESET
        elif c["statut"] == "amelioration":
            statut_str = VERT + t("baseline_amelioration") + RESET
        else:
            statut_str = VERT + t("baseline_stable") + RESET
        avant_str = (str(c["avant"]) + " ms").rjust(9)
        apres_str = (str(c["apres"]) + " ms").ljust(9)
        print("    " + c["nom"].ljust(10) + ": " + avant_str + " → " + apres_str + "  " + delta_str + "  " + statut_str)

def afficher_http_timing(ttfb_p50, transfert_p50, total_p50):
    if ttfb_p50 is None or transfert_p50 is None:
        return
    print(t("http_timing"))
    print(t("ttfb",      v=ttfb_p50))
    print(t("transfert", v=transfert_p50))
    print(t("total_p50", v=total_p50))

def afficher_resultat(r, slo_checks=None, comparaison_baseline=None):
    if r["erreur"]:
        print(r["url"] + " -> " + r["message"])
        return

    print(r["url"])
    print(t("http_dist", n=r.get("nb_mesures", "?")))
    print(t("moyenne", v=r["moyenne"], min=r["min"], max=r["max"]))
    print(t("p50",  v=r["p50"]))
    print(t("p75",  v=r["p75"]))
    print(t("p90",  v=r["p90"]))
    print(t("p95",  v=r["p95"]))
    print(t("p99",  v=r["p99"]))
    print(t("p999", v=r["p999"]))
    afficher_http_timing(r.get("ttfb_p50"), r.get("transfert_p50"), r.get("p50"))
    print(t("stabilite") + indicateur_stabilite(r["p50"], r["p99"]))
    if r.get("ip_mode"):
        print(t("dns_ip_na"))
    else:
        print(t("dns", v=r["dns_moyenne"], min=r["dns_min"], max=r["dns_max"]))

    if r.get("traceroute") is not None:
        afficher_traceroute(r["traceroute"])
    if "icmp" in r or "tcp" in r or "tls" in r:
        print("")
        afficher_protocoles(r.get("icmp"), r.get("tcp"), r.get("tls"), r.get("p50"), r["url"])

    if "cdn_info" in r:
        afficher_cdn(r["cdn_info"])
    afficher_assertions(r.get("assert_checks"))
    afficher_analyse_slo(slo_checks)
    if comparaison_baseline:
        afficher_comparaison_baseline(comparaison_baseline["lignes"], comparaison_baseline["date"])
    print("")

# ── Mesure d'un site (une itération) ─────────────────────────────────────────

def _mediane(valeurs):
    if not valeurs:
        return None
    s = sorted(valeurs)
    return round(s[len(s) // 2], 2)

def _mesurer_site(site_cfg, args, verify_tls):
    """Mesure un site et retourne le dict résultat, ou None si aucune donnée."""
    site    = site_cfg["url"]
    slo     = site_cfg.get("slo")
    asserts = site_cfg.get("assert")

    if not (site.startswith("http://") or site.startswith("https://")):
        print(t("url_invalide", url=site))
        return {"url": site, "erreur": True, "type_erreur": "url", "message": site}

    hostname = site.split("//")[-1].split("/")[0]
    is_https = site.startswith("https://")
    ip_mode  = est_adresse_ip(hostname)

    if ip_mode:
        port = 443 if is_https else 80
        joignable, msg = verifier_ip_joignable(hostname, port)
        if not joignable:
            print(t("ip_non_joignable", msg=msg))
            return {"url": site, "erreur": True, "type_erreur": "ip", "message": msg}

    hist_http        = creer_histogramme()
    mesures_dns      = []
    ttfb_mesures     = []
    transfert_mesures = []
    erreur           = None
    icmp_result      = {}
    tcp_result       = {}
    tls_result       = {}
    tr_result        = {}
    cdn_result       = {}

    icmp_thread = threading.Thread(
        target=lambda: icmp_result.update(
            {"icmp": mesurer_icmp(hostname, nb_mesures=args.nombre)}
        )
    )
    tcp_thread = threading.Thread(
        target=lambda: tcp_result.update(
            {"tcp": mesurer_tcp(site, nb_mesures=args.nombre)}
        )
    )
    tls_thread = threading.Thread(
        target=lambda: tls_result.update(
            {"tls": mesurer_tls(site, nb_mesures=args.nombre, timeout=args.timeout, verify=verify_tls)}
        )
    )
    tr_thread = threading.Thread(
        target=lambda: tr_result.update(
            {"tr": mesurer_traceroute(hostname)}
        )
    )
    cdn_thread = threading.Thread(
        target=lambda: cdn_result.update(
            {"cdn": detecter_cdn(site, timeout=args.timeout)}
        )
    )

    icmp_thread.start()
    tcp_thread.start()
    cdn_thread.start()
    if is_https:
        tls_thread.start()
    if args.traceroute:
        tr_thread.start()

    with tqdm(
        total=args.nombre,
        desc=site,
        unit="ping",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
        colour='yellow'
    ) as barre:
        for _ in range(args.nombre):
            r = mesurer_site(site, nb_mesures=1, timeout=args.timeout, verify_tls=verify_tls)
            if r["erreur"]:
                tqdm.write(site + " -> " + r["message"])
                erreur = r
                break
            hdr_enregistrer(hist_http, r["moyenne"])
            if r["dns_moyenne"] is not None:
                mesures_dns.append(r["dns_moyenne"])
            if r.get("ttfb_ms") is not None:
                ttfb_mesures.append(r["ttfb_ms"])
            if r.get("transfert_ms") is not None:
                transfert_mesures.append(r["transfert_ms"])
            barre.update(1)

    icmp_thread.join()
    tcp_thread.join()
    cdn_thread.join()
    if is_https:
        tls_thread.join()
    if args.traceroute:
        tr_thread.join()

    if erreur:
        return erreur

    if hist_http.get_total_count() == 0:
        return None

    stats      = hdr_stats(hist_http)
    icmp       = icmp_result.get("icmp")
    tcp        = tcp_result.get("tcp")
    tls        = tls_result.get("tls") if is_https else None
    traceroute = tr_result.get("tr") if args.traceroute else None
    cdn_info   = cdn_result.get("cdn")

    p50        = stats["p50"]
    p99        = stats["p99"]
    tcp_moy    = tcp["moyenne"] if tcp else None
    tls_moy    = tls["moyenne"] if tls else None
    surcharge  = round((tcp_moy or 0) + (tls_moy or 0), 1)
    http_chaud = round(p50 - surcharge, 1) if surcharge > 0 and p50 > surcharge else None

    resultat_final = {
        "url":         site,
        "erreur":      False,
        "type_erreur": None,
        "message":     None,
        "nb_mesures":  hist_http.get_total_count(),
        "ip_mode":     ip_mode,
        **stats,
        "dns_moyenne":     round(sum(mesures_dns) / len(mesures_dns), 2) if mesures_dns else None,
        "dns_min":         min(mesures_dns) if mesures_dns else None,
        "dns_max":         max(mesures_dns) if mesures_dns else None,
        "ttfb_p50":        _mediane(ttfb_mesures),
        "transfert_p50":   _mediane(transfert_mesures),
        "icmp":            icmp,
        "tcp":             tcp,
        "tls":             tls,
        "traceroute":      traceroute,
        "cdn_info":        cdn_info,
        "stabilite_ratio": round(p99 / p50, 2) if p50 > 0 else None,
        "icmp_ms":         icmp["moyenne"] if icmp else None,
        "tcp_ms":          tcp_moy,
        "tls_ms":          tls_moy,
        "http_chaud_ms":   http_chaud,
        "nb_hops":         traceroute["nb_hops"] if traceroute else None,
    }
    slo_checks    = verifier_slo(resultat_final, slo) if slo else None
    assert_checks = verifier_assertions(site, asserts, timeout=args.timeout) if asserts else None
    resultat_final["slo_checks"]    = slo_checks
    resultat_final["assert_checks"] = assert_checks

    return resultat_final

# ── Détection de dégradation ──────────────────────────────────────────────────

def detecter_degradation(current, previous):
    """Retourne la liste des métriques qui ont augmenté de plus de SEUIL_DEGRADATION."""
    alertes = []
    metriques = [
        ("p50",         current.get("p50"),         previous.get("p50")),
        ("p95",         current.get("p95"),         previous.get("p95")),
        ("p99",         current.get("p99"),         previous.get("p99")),
        ("dns_moyenne", current.get("dns_moyenne"),  previous.get("dns_moyenne")),
        ("icmp_ms",     current.get("icmp_ms"),     previous.get("icmp_ms")),
    ]
    for metric, val_curr, val_prev in metriques:
        if val_curr is None or val_prev is None or val_prev <= 0:
            continue
        delta = (val_curr - val_prev) / val_prev
        if delta >= SEUIL_DEGRADATION:
            alertes.append((metric, round(val_prev, 1), round(val_curr, 1), round(delta * 100)))
    return alertes

# ── Point d'entrée ────────────────────────────────────────────────────────────

def main():
    global t
    try:
        args, cfg = parse_arguments()
    except FileNotFoundError as e:
        print("Erreur : " + str(e), file=sys.stderr)
        sys.exit(1)

    t = get_translator(cfg.get("langue", "FR").upper())
    verify_tls = not args.no_verify_tls

    baseline = {}
    if args.baseline:
        try:
            baseline = charger_baseline(args.baseline)
        except (FileNotFoundError, ValueError) as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)

    if args.sites:
        sites_config = [{"url": s} for s in args.sites]
    else:
        sites_config = [
            s if isinstance(s, dict) else {"url": s}
            for s in cfg["sites"]
        ]

    cfg_file = args.config_file or config.FICHIER_DEFAUT
    print(t("header", ver=__version__, n=args.nombre, cfg=cfg_file) + "\n")

    tous_resultats    = []
    prev_results      = {}  # {url: resultat} — dernier résultat réussi par site
    degradation_since = {}  # {url: {metric: heure_str}} — heure de première détection

    iteration = 0
    try:
        while True:
            iteration += 1
            if args.interval:
                print(t("intervalle_titre", n=iteration, heure=_heure_scan()))

            for site_cfg in sites_config:
                r = _mesurer_site(site_cfg, args, verify_tls)
                if r is None:
                    continue

                tous_resultats.append(r)
                cmp_baseline = None
                if baseline and not r.get("erreur") and r["url"] in baseline:
                    entry = baseline[r["url"]]
                    lignes = comparer_baseline(r, entry)
                    if lignes:
                        cmp_baseline = {"lignes": lignes, "date": entry["date"]}
                r["baseline_comparaison"] = cmp_baseline
                afficher_resultat(r, r.get("slo_checks"), cmp_baseline)

                url = r["url"]
                if args.interval and not r.get("erreur") and url in prev_results:
                    heure_now = _heure_locale()
                    alertes   = detecter_degradation(r, prev_results[url])
                    if alertes:
                        degraded = set()
                        for metric, avant, apres, pct in alertes:
                            nom       = _NOMS_METRIQUES.get(metric, metric)
                            heure_deg = degradation_since.setdefault(url, {}).setdefault(metric, heure_now)
                            print(ORANGE + t("degradation_alerte", metric=nom, avant=avant, apres=apres, pct=pct, heure=heure_deg) + RESET)
                            degraded.add(metric)
                        for metric in list(degradation_since.get(url, {}).keys()):
                            if metric not in degraded:
                                del degradation_since[url][metric]
                    else:
                        degradation_since.pop(url, None)

                if not r.get("erreur"):
                    prev_results[url] = r

            if not args.interval:
                break

            print(t("intervalle_attente", s=args.interval))
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print()

    if args.csv and tous_resultats:
        fichier = sauvegarder_csv(tous_resultats)
        print(t("csv_sauvegarde", f=fichier))
        if args.baseline:
            fichier_cmp = sauvegarder_csv_comparaison(tous_resultats)
            print(t("csv_comparaison", f=fichier_cmp))

    if args.prometheus_out and tous_resultats:
        sauvegarder_prometheus(tous_resultats, args.prometheus_out)
        print(t("prometheus_sauvegarde", f=args.prometheus_out))

if __name__ == "__main__":
    main()
