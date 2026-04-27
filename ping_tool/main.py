# -*- coding: utf-8 -*-
import argparse
import sys
import threading
from tqdm import tqdm
from ping_tool import config
from ping_tool.i18n import get_translator
from ping_tool.core import (
    mesurer_site, sauvegarder_csv,
    creer_histogramme, hdr_enregistrer, hdr_stats,
    verifier_slo, mesurer_icmp, mesurer_tcp, mesurer_tls, mesurer_traceroute,
    SLO_UNITES,
)

# Codes ANSI — désactivés si la sortie n'est pas un terminal (fichier, CI)
def _ansi(code):
    return "\033[" + code + "m" if sys.stdout.isatty() else ""

VERT   = _ansi("92")
ORANGE = _ansi("33")
ROUGE  = _ansi("91")
RESET  = _ansi("0")

t = get_translator(config.LANGUE)

def parse_arguments():
    parser = argparse.ArgumentParser(
        prog="ping-tool",
        description="Mesure les temps de reponse HTTP de sites web"
    )
    parser.add_argument("--version", action="version", version="ping-tool 0.2.1")
    parser.add_argument(
        "sites", nargs="*",
        help="Sites a tester (ex: https://google.com https://github.com)"
    )
    parser.add_argument(
        "-n", "--nombre", type=int, default=config.NB_MESURES,
        help="Nombre de mesures par site (defaut: %(default)s)"
    )
    parser.add_argument("--csv", action="store_true",
        help="Sauvegarder les resultats dans un fichier CSV")
    parser.add_argument(
        "--timeout", type=int, default=config.TIMEOUT,
        help="Timeout en secondes (defaut: %(default)s)"
    )
    parser.add_argument("--traceroute", action="store_true",
        help="Afficher le nombre de hops reseau vers chaque site")
    return parser.parse_args()

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

def afficher_analyse_slo(slo_checks):
    """Affiche la section SLO Analysis groupée en fin de résultat."""
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

def afficher_resultat(r, slo_checks=None):
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
    print(t("stabilite") + indicateur_stabilite(r["p50"], r["p99"]))
    print(t("dns", v=r["dns_moyenne"], min=r["dns_min"], max=r["dns_max"]))

    if r.get("traceroute") is not None:
        afficher_traceroute(r["traceroute"])
    if "icmp" in r or "tcp" in r or "tls" in r:
        afficher_protocoles(r.get("icmp"), r.get("tcp"), r.get("tls"), r.get("p50"), r["url"])

    afficher_analyse_slo(slo_checks)
    print("")

# ── Point d'entrée ────────────────────────────────────────────────────────────

def main():
    args = parse_arguments()

    if args.sites:
        sites_config = [{"url": s} for s in args.sites]
    else:
        sites_config = [
            s if isinstance(s, dict) else {"url": s}
            for s in config.SITES_DEFAUT
        ]

    print(t("header", n=args.nombre) + "\n")

    resultats = []

    for site_cfg in sites_config:
        site = site_cfg["url"]
        slo  = site_cfg.get("slo")

        hist_http   = creer_histogramme()
        mesures_dns = []
        erreur      = None
        icmp_result = {}
        tcp_result  = {}
        tls_result  = {}
        tr_result   = {}

        hostname = site.split("//")[-1].split("/")[0]
        is_https = site.startswith("https://")

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
                {"tls": mesurer_tls(site, nb_mesures=args.nombre, timeout=args.timeout)}
            )
        )
        tr_thread = threading.Thread(
            target=lambda: tr_result.update(
                {"tr": mesurer_traceroute(hostname)}
            )
        )

        icmp_thread.start()
        tcp_thread.start()
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
                r = mesurer_site(site, nb_mesures=1, timeout=args.timeout)
                if r["erreur"]:
                    tqdm.write(site + " -> " + r["message"])
                    erreur = r
                    break
                hdr_enregistrer(hist_http, r["moyenne"])
                mesures_dns.append(r["dns_moyenne"])
                barre.update(1)

        icmp_thread.join()
        tcp_thread.join()
        if is_https:
            tls_thread.join()
        if args.traceroute:
            tr_thread.join()

        if erreur:
            resultats.append(erreur)
            continue

        if hist_http.get_total_count() > 0:
            stats    = hdr_stats(hist_http)
            icmp     = icmp_result.get("icmp")
            tcp      = tcp_result.get("tcp")
            tls      = tls_result.get("tls") if is_https else None
            traceroute = tr_result.get("tr") if args.traceroute else None

            p50      = stats["p50"]
            p99      = stats["p99"]
            tcp_moy  = tcp["moyenne"] if tcp else None
            tls_moy  = tls["moyenne"] if tls else None
            surcharge = round((tcp_moy or 0) + (tls_moy or 0), 1)
            http_chaud = round(p50 - surcharge, 1) if surcharge > 0 and p50 > surcharge else None

            resultat_final = {
                "url":        site,
                "erreur":     False,
                "type_erreur": None,
                "message":    None,
                "nb_mesures": hist_http.get_total_count(),
                **stats,
                "dns_moyenne":     round(sum(mesures_dns) / len(mesures_dns), 2),
                "dns_min":         min(mesures_dns),
                "dns_max":         max(mesures_dns),
                # objets complets (pour l'affichage protocoles)
                "icmp":       icmp,
                "tcp":        tcp,
                "tls":        tls,
                "traceroute": traceroute,
                # clés plates pour le SLO
                "stabilite_ratio": round(p99 / p50, 2) if p50 > 0 else None,
                "icmp_ms":         icmp["moyenne"] if icmp else None,
                "tcp_ms":          tcp_moy,
                "tls_ms":          tls_moy,
                "http_chaud_ms":   http_chaud,
                "nb_hops":         traceroute["nb_hops"] if traceroute else None,
            }
            slo_checks = verifier_slo(resultat_final, slo) if slo else None
            resultat_final["slo_checks"] = slo_checks

            resultats.append(resultat_final)
            afficher_resultat(resultat_final, slo_checks)

    if args.csv and resultats:
        fichier = sauvegarder_csv(resultats)
        print(t("csv_sauvegarde", f=fichier))

if __name__ == "__main__":
    main()
