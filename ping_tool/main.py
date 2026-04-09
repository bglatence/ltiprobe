# -*- coding: utf-8 -*-
from ping_tool import config
from ping_tool.core import mesurer_site, sauvegarder_csv

def afficher_resultat(r):
    if r["erreur"]:
        print(r["url"] + " -> Erreur")
    else:
        print(r["url"] + " -> " + str(r["moyenne"]) + " ms"
              + "  (min: " + str(r["min"]) + "  max: " + str(r["max"]) + ")")

def main():
    print("Mesure des temps de reponse...\n")
    resultats = []
    for site in config.SITES_DEFAUT:
        r = mesurer_site(site)
        afficher_resultat(r)
        resultats.append(r)
    fichier = sauvegarder_csv(resultats)
    print("\nResultats sauvegardes dans : " + fichier)

if __name__ == "__main__":
    main()