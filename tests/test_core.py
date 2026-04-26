# -*- coding: utf-8 -*-
from ping_tool.core import mesurer_site, sauvegarder_csv, creer_histogramme, hdr_enregistrer, hdr_stats, verifier_slo
import os

def test_hdr_stats_percentiles_croissants():
    """Les percentiles doivent être croissants."""
    hist = creer_histogramme()
    for ms in [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]:
        hdr_enregistrer(hist, ms)
    s = hdr_stats(hist)
    assert s["p50"] <= s["p75"] <= s["p90"] <= s["p95"] <= s["p99"] <= s["p999"]

def test_hdr_stats_valeur_unique():
    """Avec une seule mesure, tous les percentiles doivent être égaux."""
    hist = creer_histogramme()
    hdr_enregistrer(hist, 42.5)
    s = hdr_stats(hist)
    assert s["p50"] == s["p95"] == s["p99"]

def test_hdr_stats_contient_encode():
    """hdr_stats doit inclure la clé hdr_encode non vide."""
    hist = creer_histogramme()
    hdr_enregistrer(hist, 50.0)
    s = hdr_stats(hist)
    assert "hdr_encode" in s
    assert len(s["hdr_encode"]) > 0

def test_mesurer_site_valide():
    """Un site valide doit retourner HTTP, DNS et la distribution complète."""
    r = mesurer_site("https://google.com", nb_mesures=1)
    assert not r["erreur"]
    assert r["moyenne"] > 0
    assert r["dns_moyenne"] > 0
    for cle in ["p50", "p75", "p90", "p95", "p99", "p999", "hdr_encode"]:
        assert cle in r, f"Clé manquante : {cle}"

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
    assert r["erreur"]
    assert r["type_erreur"] in ["timeout", "inconnu", "http"]

def test_mesurer_site_url_malformee():
    """Une URL malformee doit retourner une erreur."""
    r = mesurer_site("pas-une-url", nb_mesures=1)
    assert r["erreur"]

def test_verifier_slo_respect():
    """Un résultat sous les seuils doit tout marquer OK."""
    resultat = {"p50": 100.0, "p95": 200.0, "dns_moyenne": 10.0}
    slo = {"http_p50_ms": 200, "http_p95_ms": 400, "dns_ms": 50}
    checks = verifier_slo(resultat, slo)
    assert all(c["ok"] for c in checks.values())

def test_verifier_slo_violation():
    """Un résultat au-dessus d'un seuil doit marquer ce seuil en violation."""
    resultat = {"p50": 250.0, "p95": 200.0, "dns_moyenne": 10.0}
    slo = {"http_p50_ms": 200, "http_p95_ms": 400, "dns_ms": 50}
    checks = verifier_slo(resultat, slo)
    assert not checks["http_p50_ms"]["ok"]
    assert checks["http_p95_ms"]["ok"]
    assert checks["dns_ms"]["ok"]

def test_verifier_slo_cle_inconnue():
    """Une clé SLO inconnue doit être ignorée silencieusement."""
    resultat = {"p50": 100.0}
    slo = {"cle_inexistante": 999}
    checks = verifier_slo(resultat, slo)
    assert checks == {}

def test_verifier_slo_vide():
    """Un SLO vide doit retourner un dict vide."""
    resultat = {"p50": 100.0}
    checks = verifier_slo(resultat, {})
    assert checks == {}

def test_sauvegarder_csv(tmp_path):
    """Le CSV doit contenir les colonnes de distribution et hdr_encode."""
    hist = creer_histogramme()
    hdr_enregistrer(hist, 100.0)
    stats = hdr_stats(hist)
    resultats = [{
        "url": "https://test.com",
        "erreur": False,
        "type_erreur": None,
        "message": None,
        "dns_moyenne": 8.5,
        "dns_min": 7.1,
        "dns_max": 9.8,
        **stats,
    }]
    fichier = sauvegarder_csv(resultats, str(tmp_path / "test.csv"))
    assert os.path.exists(fichier)
    with open(fichier) as f:
        contenu = f.read()
    for col in ["url", "p50", "p95", "p99", "hdr_encode", "dns_moyenne"]:
        assert col in contenu, f"Colonne manquante dans le CSV : {col}"
    assert "https://test.com" in contenu
