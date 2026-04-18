# -*- coding: utf-8 -*-
from ping_tool.core import mesurer_site, sauvegarder_csv
import os

def test_mesurer_site_valide():
    """Un site valide doit retourner HTTP et DNS."""
    r = mesurer_site("https://google.com", nb_mesures=1)
    assert r["erreur"] == False
    assert r["moyenne"] > 0
    assert r["dns_moyenne"] > 0
    assert r["dns_moyenne"] < r["moyenne"]  # DNS doit être plus rapide que HTTP

def test_mesurer_dns_valide():
    """La resolution DNS d'un site valide doit reussir."""
    from ping_tool.core import mesurer_dns
    ms = mesurer_dns("google.com")
    assert ms is not None
    assert ms > 0

def test_mesurer_dns_invalide():
    """La resolution DNS d'un faux site doit retourner None."""
    from ping_tool.core import mesurer_dns
    ms = mesurer_dns("slkjddslfj.com")
    assert ms is None

def test_mesurer_site_timeout():
    """Un timeout tres court doit retourner une erreur."""
    r = mesurer_site("https://google.com", nb_mesures=1, timeout=0.001)
    assert r["erreur"] == True
    assert r["type_erreur"] in ["timeout", "inconnu", "http"]

def test_mesurer_site_url_malformee():
    """Une URL malformee doit retourner une erreur."""
    r = mesurer_site("pas-une-url", nb_mesures=1)
    assert r["erreur"] == True

def test_sauvegarder_csv(tmp_path):
    """Le CSV doit etre cree avec les bonnes colonnes."""
    resultats = [{
        "url": "https://test.com",
        "erreur": False,
        "type_erreur": None,
        "message": None,
        "moyenne": 100,
        "min": 90,
        "max": 110,
        "mesures": [100],
        "dns_moyenne": 8.5,
        "dns_min": 7.1,
        "dns_max": 9.8,
    }]
    fichier = sauvegarder_csv(resultats, str(tmp_path / "test.csv"))
    assert os.path.exists(fichier)
    with open(fichier) as f:
        contenu = f.read()
    assert "url" in contenu
    assert "dns_moyenne" in contenu
    assert "https://test.com" in contenu