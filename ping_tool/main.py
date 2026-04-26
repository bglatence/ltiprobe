# -*- coding: utf-8 -*-
import argparse
from tqdm import tqdm
from ping_tool import config
from ping_tool.core import (
    mesurer_site, sauvegarder_csv,
    creer_histogramme, hdr_enregistrer, hdr_stats,
    verifier_slo,
)

def parse_arguments():
    parser = argparse.ArgumentParser(
        prog="ping-tool",
        description="Mesure les temps de reponse HTTP de sites web"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="ping-tool 0.2.1"
    )
    parser.add_argument(
        "sites",
        nargs="*",
        help="Sites a tester (ex: https://google.com https://github.com)"
    )
    parser.add_argument(
        "-n", "--nombre",
        type=int,
        default=config.NB_MESURES,
        help="Nombre de mesures par site (defaut: %(default)s)"
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Sauvegarder les resultats dans un fichier CSV"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=config.TIMEOUT,
        help="Timeout en secondes (defaut: %(default)s)"
    )
    return parser.parse_args()

def indicateur_stabilite(p50, p99):
    """Evalue la stabilite a partir du ratio p99/p50."""
    if p50 <= 0:
        return "n/a"
    ratio = p99 / p50
    if ratio < 2:
        return "tres stable  (p99/p50 = " + str(round(ratio, 1)) + "x)"
    if ratio < 5:
        return "stable       (p99/p50 = " + str(round(ratio, 1)) + "x)"
    if ratio < 10:
        return "variable     (p99/p50 = " + str(round(ratio, 1)) + "x)"
    return "instable     (p99/p50 = " + str(round(ratio, 1)) + "x)"

def _slo_tag(slo_checks, cle_slo):
    """Retourne le tag SLO inline pour une clé, ou chaîne vide si absent."""
    if not slo_checks or cle_slo not in slo_checks:
        return ""
    c = slo_checks[cle_slo]
    statut = "OK" if c["ok"] else "VIOLATION"
    return "  [SLO <=" + str(c["seuil"]) + "ms  " + statut + "]"

def afficher_resultat(r, slo_checks=None):
    if r["erreur"]:
        print(r["url"] + " -> " + r["message"])
        return

    print(r["url"])
    print("  HTTP  distribution (" + str(r.get("nb_mesures", "?")) + " mesures)")
    print("    moyenne : " + str(r["moyenne"]) + " ms"
          + "   min: " + str(r["min"]) + "   max: " + str(r["max"]))
    print("    p50     : " + str(r["p50"])  + " ms" + _slo_tag(slo_checks, "http_p50_ms"))
    print("    p75     : " + str(r["p75"])  + " ms" + _slo_tag(slo_checks, "http_p75_ms"))
    print("    p90     : " + str(r["p90"])  + " ms" + _slo_tag(slo_checks, "http_p90_ms"))
    print("    p95     : " + str(r["p95"])  + " ms" + _slo_tag(slo_checks, "http_p95_ms"))
    print("    p99     : " + str(r["p99"])  + " ms" + _slo_tag(slo_checks, "http_p99_ms"))
    print("    p99.9   : " + str(r["p999"]) + " ms" + _slo_tag(slo_checks, "http_p999_ms"))
    print("  Stabilite : " + indicateur_stabilite(r["p50"], r["p99"]))
    print("  DNS   -> moyenne: " + str(r["dns_moyenne"]) + " ms"
          + "  min: " + str(r["dns_min"]) + "  max: " + str(r["dns_max"])
          + _slo_tag(slo_checks, "dns_ms"))

    if slo_checks:
        nb_violations = sum(1 for c in slo_checks.values() if not c["ok"])
        if nb_violations == 0:
            print("  SLO   -> tous les objectifs sont respectes")
        else:
            print("  SLO   -> " + str(nb_violations) + " violation(s)")
    print("")

def main():
    args = parse_arguments()

    # Les sites passés en CLI (strings) n'ont pas de SLO
    if args.sites:
        sites_config = [{"url": s} for s in args.sites]
    else:
        sites_config = [
            s if isinstance(s, dict) else {"url": s}
            for s in config.SITES_DEFAUT
        ]

    print("Mesure des temps de reponse (" + str(args.nombre) + " essais)...\n")

    resultats = []

    for site_cfg in sites_config:
        site = site_cfg["url"]
        slo  = site_cfg.get("slo")

        hist_http = creer_histogramme()
        mesures_dns = []
        erreur = None

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

        if erreur:
            resultats.append(erreur)
            continue

        if hist_http.get_total_count() > 0:
            stats = hdr_stats(hist_http)
            resultat_final = {
                "url": site,
                "erreur": False,
                "type_erreur": None,
                "message": None,
                "nb_mesures": hist_http.get_total_count(),
                **stats,
                "dns_moyenne": round(sum(mesures_dns) / len(mesures_dns), 2),
                "dns_min":     min(mesures_dns),
                "dns_max":     max(mesures_dns),
            }
            slo_checks = verifier_slo(resultat_final, slo) if slo else None
            resultat_final["slo_checks"] = slo_checks

            resultats.append(resultat_final)
            afficher_resultat(resultat_final, slo_checks)

    if args.csv and resultats:
        fichier = sauvegarder_csv(resultats)
        print("Resultats sauvegardes dans : " + fichier)

if __name__ == "__main__":
    main()
