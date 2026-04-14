# -*- coding: utf-8 -*-
from ping_tool.core import mesurer_site, sauvegarder_csv
import os

def test_mesurer_site_valide():
    """Un site valide doit retourner un resultat sans erreur."""
    r = mesurer_site("https://google.com", nb_mesures=1)
    assert r["erreur"] == False
    assert r["moyenne"] > 0
    assert r["min"] <= r["moyenne"] <= r["max"]

def test_mesurer_site_dns_invalide():
    """Un site avec DNS invalide doit retourner une erreur DNS."""
    r = mesurer_site("https://slkjddslfj.com", nb_mesures=1)
    assert r["erreur"] == True
    assert r["type_erreur"] == "dns"
    assert "resoudre" in r["message"].lower()

def test_mesurer_site_timeout():
    """Un timeout tres court doit retourner une erreur timeout."""
    r = mesurer_site("https://google.com", nb_mesures=1, timeout=0.001)
    assert r["erreur"] == True
    assert r["type_erreur"] in ["timeout", "inconnu"]

def test_mesurer_site_url_malformee():
    """Une URL malformee doit retourner une erreur."""
    r = mesurer_site("pas-une-url", nb_mesures=1)
    assert r["erreur"] == True

def test_sauvegarder_csv(tmp_path):
    """Le CSV doit etre cree avec les bonnes colonnes."""
    resultats = [{"url": "https://test.com", "erreur": False,
                  "moyenne": 100, "min": 90, "max": 110, "mesures": [100]}]
    fichier = sauvegarder_csv(resultats, str(tmp_path / "test.csv"))
    assert os.path.exists(fichier)
    with open(fichier) as f:
        contenu = f.read()
    assert "url" in contenu
    assert "https://test.com" in contenu