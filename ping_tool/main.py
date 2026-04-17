# -*- coding: utf-8 -*-
import argparse
from tqdm import tqdm
from ping_tool import config
from ping_tool.core import mesurer_site, sauvegarder_csv

def parse_arguments():
    parser = argparse.ArgumentParser(
        prog="ping-tool",
        description="Mesure les temps de reponse HTTP de sites web"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="ping-tool 0.1.0"
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

def afficher_resultat(r):
    if r["erreur"]:
        print(r["url"] + " -> " + r["message"])
    else:
        print(r["url"])
        print("  HTTP  -> moyenne: " + str(r["moyenne"]) + " ms"
              + "  min: " + str(r["min"]) + "  max: " + str(r["max"]))
        print("  DNS   -> moyenne: " + str(r["dns_moyenne"]) + " ms"
              + "  min: " + str(r["dns_min"]) + "  max: " + str(r["dns_max"]))
        print("  DNS % -> " + str(round(r["dns_moyenne"] / r["moyenne"] * 100, 1))
              + "% du temps total")
        print("")

def main():
    args = parse_arguments()
    sites = args.sites if args.sites else config.SITES_DEFAUT

    print("Mesure des temps de reponse (" + str(args.nombre) + " essais)...\n")

    resultats = []

    # Barre de progression par site
    for site in sites:
        mesures_http = []
        mesures_dns = []

        with tqdm(
            total=args.nombre,
            desc=site,
            unit="ping",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]", colour='yellow'
        ) as barre:
            for _ in range(args.nombre):
                r = mesurer_site(site, nb_mesures=1, timeout=args.timeout)
                if r["erreur"]:
                    tqdm.write(site + " -> " + r["message"])
                    break
                mesures_http.append(r["moyenne"])
                mesures_dns.append(r["dns_moyenne"])
                barre.update(1)

        if mesures_http:
            resultat_final = {
                "url": site,
                "erreur": False,
                "type_erreur": None,
                "message": None,
                "moyenne": round(sum(mesures_http) / len(mesures_http), 2),
                "min": min(mesures_http),
                "max": max(mesures_http),
                "mesures": mesures_http,
                "dns_moyenne": round(sum(mesures_dns) / len(mesures_dns), 2),
                "dns_min": min(mesures_dns),
                "dns_max": max(mesures_dns),
            }
            resultats.append(resultat_final)
            afficher_resultat(resultat_final)

    if args.csv and resultats:
        fichier = sauvegarder_csv(resultats)
        print("Resultats sauvegardes dans : " + fichier)

if __name__ == "__main__":
    main()