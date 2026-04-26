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
    checks = verifier_slo(resultat, {"cle_inexistante": 999})
    assert checks == {}

def test_verifier_slo_vide():
    """Un SLO vide doit retourner un dict vide."""
    checks = verifier_slo({"p50": 100.0}, {})
    assert checks == {}

def test_config_yaml(tmp_path):
    """Le chargeur YAML doit lire nb_mesures et les sites correctement."""
    yaml_content = (
        "nb_mesures: 5\n"
        "timeout: 3\n"
        "sites:\n"
        "  - url: https://example.com\n"
        "    slo:\n"
        "      http_p50_ms: 100\n"
    )
    config_file = tmp_path / "ping-tool.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")

    import yaml
    data = yaml.safe_load(config_file.read_text())
    assert data["nb_mesures"] == 5
    assert data["timeout"] == 3
    assert data["sites"][0]["url"] == "https://example.com"
    assert data["sites"][0]["slo"]["http_p50_ms"] == 100

_CLES_SLO_VALIDES = {
    "http_p50_ms", "http_p75_ms", "http_p90_ms",
    "http_p95_ms", "http_p99_ms", "http_p999_ms", "dns_ms",
}

def test_ping_tool_yaml_existe():
    """Le fichier ping-tool.yaml doit exister à la racine du projet."""
    assert os.path.exists("ping-tool.yaml"), "ping-tool.yaml introuvable à la racine"

def test_ping_tool_yaml_structure():
    """ping-tool.yaml doit avoir les clés obligatoires avec les bons types."""
    import yaml
    with open("ping-tool.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert isinstance(data.get("nb_mesures"), int), "nb_mesures doit être un entier"
    assert data["nb_mesures"] > 0, "nb_mesures doit être > 0"
    assert isinstance(data.get("timeout"), int), "timeout doit être un entier"
    assert data["timeout"] > 0, "timeout doit être > 0"
    assert isinstance(data.get("sites"), list), "sites doit être une liste"
    assert len(data["sites"]) > 0, "sites ne doit pas être vide"

def test_ping_tool_yaml_sites():
    """Chaque site dans ping-tool.yaml doit avoir une URL valide."""
    import yaml
    with open("ping-tool.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for site in data["sites"]:
        assert "url" in site, f"Site sans clé 'url' : {site}"
        url = site["url"]
        assert url.startswith("http://") or url.startswith("https://"), \
            f"URL invalide (doit commencer par http:// ou https://) : {url}"

def test_ping_tool_yaml_slo_cles():
    """Les clés SLO dans ping-tool.yaml doivent être reconnues par verifier_slo."""
    import yaml
    with open("ping-tool.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for site in data["sites"]:
        slo = site.get("slo")
        if not slo:
            continue
        cles_inconnues = set(slo.keys()) - _CLES_SLO_VALIDES
        assert not cles_inconnues, \
            f"Clés SLO inconnues pour {site['url']} : {cles_inconnues}"
        for cle, valeur in slo.items():
            assert isinstance(valeur, (int, float)) and valeur > 0, \
                f"Seuil SLO invalide pour {site['url']}.{cle} : {valeur}"

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
