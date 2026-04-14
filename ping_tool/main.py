# -*- coding: utf-8 -*-
import argparse
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
        print(r["url"] + " -> " + str(r["moyenne"]) + " ms"
              + "  (min: " + str(r["min"]) + "  max: " + str(r["max"]) + ")")

def main():

    args = parse_arguments()

    # utilise les site passés en args sinon ceux dans config.py
    sites = args.sites if args.sites else config.SITES_DEFAUT

    print("Mesure des temps de reponse (" + str(args.nombre) + " essais)...\n")

    resultats = []
    for site in sites:
        r = mesurer_site(site, nb_mesures=args.nombre, timeout=args.timeout)
        afficher_resultat(r)
        resultats.append(r)

    if args.csv:
        fichier = sauvegarder_csv(resultats)
        print("\nResultats sauvegardes dans : " + fichier)

if __name__ == "__main__":
    main()