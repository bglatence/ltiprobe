# -*- coding: utf-8 -*-
import os
import pytest
from ltiprobe.core import mesurer_site, sauvegarder_csv, sauvegarder_prometheus, envoyer_webhook, calculer_mos, creer_histogramme, hdr_enregistrer, hdr_stats, verifier_slo, verifier_assertions, charger_baseline, comparer_baseline, sauvegarder_csv_comparaison, inspecter_tls
from ltiprobe.i18n import get_translator


def test_i18n_fr_header():
    """Le traducteur FR doit produire un message en français."""
    t = get_translator("FR")
    assert "essais" in t("header", ver="0.3.0", n=5, cfg="ltiprobe.yaml")

def test_i18n_en_header():
    """Le traducteur EN doit produire un message en anglais."""
    t = get_translator("EN")
    assert "attempts" in t("header", ver="0.3.0", n=5, cfg="ltiprobe.yaml")

def test_i18n_langue_inconnue_repli_fr():
    """Une langue inconnue doit utiliser le français par défaut."""
    t = get_translator("ZZ")
    assert "essais" in t("header", ver="0.3.0", n=5, cfg="ltiprobe.yaml")

def test_i18n_cles_identiques():
    """FR et EN doivent avoir exactement les mêmes clés."""
    from ltiprobe.i18n import _TRANSLATIONS
    assert set(_TRANSLATIONS["FR"].keys()) == set(_TRANSLATIONS["EN"].keys())

def test_verifier_assertions_status_ok():
    """Un site retournant 200 doit valider status_code: 200."""
    checks = verifier_assertions("https://google.com", {"status_code": 200})
    assert "_erreur" not in checks
    assert checks["status_code"]["ok"]

def test_verifier_assertions_status_violation():
    """Un status_code incorrect doit être marqué en violation."""
    checks = verifier_assertions("https://google.com", {"status_code": 999})
    assert not checks["status_code"]["ok"]

def test_verifier_assertions_body_contains_ok():
    """La recherche d'un mot présent dans le body doit réussir."""
    checks = verifier_assertions("https://google.com", {"body_contains": "google"})
    assert checks["body_contains"]["ok"]

def test_verifier_assertions_body_contains_violation():
    """La recherche d'un mot absent doit échouer."""
    checks = verifier_assertions("https://google.com", {"body_contains": "xyzxyzxyz_absent_xyzxyz"})
    assert not checks["body_contains"]["ok"]

def test_verifier_assertions_host_invalide():
    """Un hôte inexistant doit retourner une erreur."""
    checks = verifier_assertions("https://hote.inexistant.invalid", {"status_code": 200})
    assert "_erreur" in checks

def test_verifier_assertions_vide():
    """Des assertions vides doivent retourner un dict vide."""
    checks = verifier_assertions("https://google.com", {})
    assert checks == {}

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

def test_hdr_enregistrer_sans_correction():
    """Sans intervalle_us, record_value() est utilisé — count == nb insertions."""
    hist = creer_histogramme()
    hdr_enregistrer(hist, 100.0)
    hdr_enregistrer(hist, 200.0)
    assert hist.get_total_count() == 2

def test_hdr_enregistrer_avec_correction_insere_valeurs_supplementaires():
    """Avec intervalle_us, une mesure très lente doit générer plus d'une entrée."""
    hist = creer_histogramme()
    # intervalle attendu : 1000ms (1_000_000 µs), mesure : 3500ms → doit insérer 3+ valeurs
    hdr_enregistrer(hist, 3500.0, intervalle_us=1_000_000)
    assert hist.get_total_count() >= 3

def test_hdr_enregistrer_avec_correction_eleve_p99():
    """La correction doit produire un p99 plus élevé qu'un enregistrement brut."""
    hist_brut   = creer_histogramme()
    hist_corr   = creer_histogramme()
    intervalle_us = 500_000  # 500ms entre mesures
    mesures = [200.0, 200.0, 200.0, 200.0, 200.0, 200.0, 200.0, 200.0, 200.0, 3000.0]
    for ms in mesures:
        hdr_enregistrer(hist_brut, ms)
        hdr_enregistrer(hist_corr, ms, intervalle_us=intervalle_us)
    assert hdr_stats(hist_corr)["p99"] >= hdr_stats(hist_brut)["p99"]

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

def test_verifier_slo_stabilite_ratio():
    """stabilite_ratio doit vérifier p99/p50 par rapport au seuil."""
    resultat = {"p50": 100.0, "p99": 200.0, "stabilite_ratio": 2.0}
    checks = verifier_slo(resultat, {"stabilite_ratio": 3.0})
    assert checks["stabilite_ratio"]["ok"]
    checks2 = verifier_slo(resultat, {"stabilite_ratio": 1.5})
    assert not checks2["stabilite_ratio"]["ok"]

def test_verifier_slo_nouvelles_cles():
    """icmp_ms, tcp_ms, tls_ms et http_chaud_ms doivent être vérifiables."""
    resultat = {
        "icmp_ms": 12.0, "tcp_ms": 18.0,
        "tls_ms": 45.0, "http_chaud_ms": 70.0,
    }
    slo = {"icmp_ms": 20, "tcp_ms": 30, "tls_ms": 50, "http_chaud_ms": 100}
    checks = verifier_slo(resultat, slo)
    assert all(c["ok"] for c in checks.values())

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
    config_file = tmp_path / "ltiprobe.yaml"
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
    "stabilite_ratio", "icmp_ms", "icmp_jitter_ms", "icmp_loss_pct",
    "tcp_ms", "tcp_jitter_ms", "tls_ms",
    "http_chaud_ms", "nb_hops_max", "mos_min",
}

def test_ltiprobe_yaml_existe():
    """Le fichier ltiprobe.yaml doit exister à la racine du projet."""
    assert os.path.exists("ltiprobe.yaml"), "ltiprobe.yaml introuvable à la racine"

def test_ltiprobe_yaml_structure():
    """ltiprobe.yaml doit avoir les clés obligatoires avec les bons types."""
    import yaml
    with open("ltiprobe.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert isinstance(data.get("nb_mesures"), int), "nb_mesures doit être un entier"
    assert data["nb_mesures"] > 0, "nb_mesures doit être > 0"
    assert isinstance(data.get("timeout"), int), "timeout doit être un entier"
    assert data["timeout"] > 0, "timeout doit être > 0"
    assert isinstance(data.get("sites"), list), "sites doit être une liste"
    assert len(data["sites"]) > 0, "sites ne doit pas être vide"

def test_ltiprobe_yaml_sites():
    """Chaque site dans ltiprobe.yaml doit avoir une URL valide."""
    import yaml
    with open("ltiprobe.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for site in data["sites"]:
        assert "url" in site, f"Site sans clé 'url' : {site}"
        url = site["url"]
        assert url.startswith("http://") or url.startswith("https://"), \
            f"URL invalide (doit commencer par http:// ou https://) : {url}"

def test_ltiprobe_yaml_slo_cles():
    """Les clés SLO dans ltiprobe.yaml doivent être reconnues par verifier_slo."""
    import yaml
    with open("ltiprobe.yaml", encoding="utf-8") as f:
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

def test_calculer_mos_excellent():
    """Conditions idéales → MOS ≥ 4.3 (excellente)."""
    r = calculer_mos(20.0, 1.0, 0.0)
    assert r["mos"] >= 4.3
    assert r["qualite"] == "excellente"
    assert 80 <= r["r_factor"] <= 100


def test_calculer_mos_mauvais():
    """Forte latence + perte → MOS < 3.1 (mauvaise)."""
    r = calculer_mos(400.0, 30.0, 5.0)
    assert r["mos"] < 3.1
    assert r["qualite"] == "mauvaise"


def test_calculer_mos_sans_jitter_loss():
    """Sans jitter ni perte, seule la latence dégrade le score."""
    r_faible  = calculer_mos(20.0)
    r_elevee  = calculer_mos(300.0)
    assert r_faible["mos"] > r_elevee["mos"]


def test_calculer_mos_plafond():
    """Le MOS ne peut pas dépasser 4.5 ni descendre sous 1.0."""
    r_ideal = calculer_mos(1.0, 0.0, 0.0)
    r_pire  = calculer_mos(5000.0, 500.0, 100.0)
    assert r_ideal["mos"] <= 4.5
    assert r_pire["mos"] >= 1.0


def test_calculer_mos_seuils_qualite():
    """Chaque niveau de qualité doit être atteignable."""
    niveaux = {
        calculer_mos(20.0, 1.0, 0.0)["qualite"],     # excellente
        calculer_mos(80.0, 5.0, 0.0)["qualite"],     # bonne
        calculer_mos(150.0, 10.0, 1.0)["qualite"],   # acceptable
        calculer_mos(250.0, 20.0, 3.0)["qualite"],   # mediocre
        calculer_mos(400.0, 30.0, 5.0)["qualite"],   # mauvaise
    }
    assert "excellente" in niveaux
    assert "mauvaise"   in niveaux


def test_verifier_slo_mos_min_respect():
    """mos_min : MOS >= seuil → ok=True, op='>='."""
    resultat = {"mos": 4.1}
    checks = verifier_slo(resultat, {"mos_min": 4.0})
    assert checks["mos_min"]["ok"] is True
    assert checks["mos_min"]["op"] == ">="


def test_verifier_slo_mos_min_violation():
    """mos_min : MOS < seuil → ok=False."""
    resultat = {"mos": 3.5}
    checks = verifier_slo(resultat, {"mos_min": 4.0})
    assert checks["mos_min"]["ok"] is False
    assert checks["mos_min"]["op"] == ">="


def test_verifier_slo_op_field_standard():
    """Les clés SLO standards doivent avoir op='<='."""
    resultat = {"p50": 100.0, "dns_moyenne": 30.0}
    checks = verifier_slo(resultat, {"http_p50_ms": 200, "dns_ms": 50})
    assert checks["http_p50_ms"]["op"] == "<="
    assert checks["dns_ms"]["op"] == "<="


def test_jitter_calcul():
    """_jitter doit calculer l'écart-type correct."""
    from ltiprobe.core import _jitter
    assert _jitter([10.0, 10.0, 10.0]) == 0.0
    assert _jitter([10.0, 20.0]) == 5.0
    assert _jitter([10.0]) is None
    assert _jitter([]) is None


def test_jitter_valeurs_asymetriques():
    """_jitter doit être insensible à l'ordre des valeurs."""
    from ltiprobe.core import _jitter
    j1 = _jitter([10.0, 20.0, 30.0])
    j2 = _jitter([30.0, 10.0, 20.0])
    assert j1 == j2
    assert j1 > 0


def test_mesurer_tcp_valide():
    """Un hôte accessible doit retourner des RTTs TCP positifs avec jitter."""
    from ltiprobe.core import mesurer_tcp
    r = mesurer_tcp("https://google.com", nb_mesures=3)
    assert r is not None
    assert r["moyenne"] > 0
    assert r["min"] <= r["moyenne"] <= r["max"]
    assert r["nb"] == 3
    assert r["port"] == 443
    assert "jitter" in r

def test_mesurer_tcp_invalide():
    """Un hôte inexistant doit retourner None."""
    from ltiprobe.core import mesurer_tcp
    r = mesurer_tcp("https://hote.inexistant.invalid", nb_mesures=1)
    assert r is None

def test_mesurer_tls_valide():
    """Un site HTTPS accessible doit retourner des temps de handshake positifs."""
    from ltiprobe.core import mesurer_tls
    r = mesurer_tls("https://google.com", nb_mesures=2)
    assert r is not None
    assert r["moyenne"] > 0
    assert r["min"] <= r["moyenne"] <= r["max"]
    assert r["nb"] == 2

@pytest.mark.skipif(os.getenv("CI") == "true", reason="traceroute bloqué en CI")
def test_mesurer_traceroute_valide():
    """Un hôte accessible doit retourner un nombre de hops positif."""
    from ltiprobe.core import mesurer_traceroute
    r = mesurer_traceroute("google.com", max_hops=30)
    assert r is not None
    assert r["nb_hops"] > 0
    assert r["nb_repondus"] >= 0
    assert r["nb_masques"] >= 0
    assert r["nb_repondus"] + r["nb_masques"] == r["nb_hops"]

def test_mesurer_traceroute_invalide():
    """Un hôte inexistant doit retourner None."""
    from ltiprobe.core import mesurer_traceroute
    r = mesurer_traceroute("hote.inexistant.invalid", max_hops=3)
    assert r is None

def test_mesurer_tls_invalide():
    """Un hôte inexistant doit retourner None."""
    from ltiprobe.core import mesurer_tls
    r = mesurer_tls("https://hote.inexistant.invalid", nb_mesures=1)
    assert r is None

@pytest.mark.skipif(os.getenv("CI") == "true", reason="ICMP bloqué en CI")
def test_mesurer_icmp_valide():
    """Un hôte accessible doit retourner des RTTs positifs avec jitter et loss."""
    from ltiprobe.core import mesurer_icmp
    r = mesurer_icmp("google.com", nb_mesures=5)
    assert r is not None
    assert r["moyenne"] > 0
    assert r["min"] <= r["moyenne"] <= r["max"]
    assert r["nb"] == 5
    assert "jitter" in r
    assert "loss_pct" in r
    assert 0.0 <= r["loss_pct"] <= 100.0

def test_mesurer_icmp_invalide():
    """Un hôte inexistant doit retourner None."""
    from ltiprobe.core import mesurer_icmp
    r = mesurer_icmp("hote.inexistant.invalid", nb_mesures=1)
    assert r is None

def test_verifier_ip_joignable_ok():
    """Une IP publique accessible sur le port 443 doit être joignable."""
    from ltiprobe.core import verifier_ip_joignable
    ok, msg = verifier_ip_joignable("8.8.8.8", 443)
    assert ok
    assert msg is None

def test_verifier_ip_joignable_echec():
    """Une IP non routable doit retourner non joignable rapidement."""
    from ltiprobe.core import verifier_ip_joignable
    ok, msg = verifier_ip_joignable("192.168.99.99", 80, timeout=2)
    assert not ok
    assert msg is not None

def test_est_adresse_ip():
    """est_adresse_ip doit distinguer IP et nom de domaine."""
    from ltiprobe.core import est_adresse_ip
    assert est_adresse_ip("8.8.8.8")
    assert est_adresse_ip("2001:4860:4860::8888")  # IPv6
    assert not est_adresse_ip("google.com")
    assert not est_adresse_ip("192.168.x.x")  # invalide

def test_mesurer_site_ip_dns_na():
    """Un site accédé par IP ne doit pas avoir de mesure DNS."""
    r = mesurer_site("http://93.184.216.34", nb_mesures=1)
    # Succès ou erreur réseau selon l'environnement, mais jamais d'erreur DNS
    if not r["erreur"]:
        assert r["ip_mode"] is True
        assert r["dns_moyenne"] is None

def test_detecter_cdn_retourne_dict():
    """detecter_cdn sur un site accessible doit retourner un dict avec les clés attendues."""
    from ltiprobe.core import detecter_cdn
    r = detecter_cdn("https://google.com")
    assert r is not None
    for cle in ("cdn", "cache", "age_s", "pop", "via"):
        assert cle in r, f"Clé manquante : {cle}"

def test_detecter_cdn_invalide():
    """Un hôte inexistant doit retourner None."""
    from ltiprobe.core import detecter_cdn
    r = detecter_cdn("https://hote.inexistant.invalid")
    assert r is None

def test_detecter_cdn_cloudflare():
    """Un site derrière Cloudflare doit être détecté."""
    from ltiprobe.core import detecter_cdn
    r = detecter_cdn("https://www.cloudflare.com")
    assert r is not None
    assert r["cdn"] == "Cloudflare"


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
    from ltiprobe.core import mesurer_dns
    ms = mesurer_dns("google.com")
    assert ms is not None
    assert ms > 0

def test_mesurer_dns_invalide():
    """La resolution DNS d'un faux site doit retourner None."""
    from ltiprobe.core import mesurer_dns
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
    for col in ["url", "p50", "p95", "p99", "hdr_encode", "dns_moyenne", "ttfb_p50", "transfert_p50"]:
        assert col in contenu, f"Colonne manquante dans le CSV : {col}"
    assert "https://test.com" in contenu


def test_envoyer_webhook_succes():
    """envoyer_webhook() doit retourner True si le serveur répond."""
    from unittest.mock import patch, MagicMock
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
        result = envoyer_webhook("https://example.com/hook", {"event": "test"})
    assert result is True
    mock_open.assert_called_once()


def test_envoyer_webhook_echec():
    """envoyer_webhook() doit retourner False si le serveur est injoignable."""
    from unittest.mock import patch
    with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
        result = envoyer_webhook("https://example.com/hook", {"event": "test"})
    assert result is False


def test_envoyer_webhook_payload_json():
    """envoyer_webhook() doit envoyer un Content-Type application/json."""
    from unittest.mock import patch, MagicMock
    appels = []
    def fake_urlopen(req, timeout):
        appels.append(req)
        return MagicMock(__enter__=lambda s: s, __exit__=MagicMock(return_value=False))
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        envoyer_webhook("https://example.com/hook", {"url": "https://test.com", "event": "slo_violation"})
    assert appels
    assert appels[0].get_header("Content-type") == "application/json"


def test_inspecter_tls_valide():
    """inspecter_tls() sur un site HTTPS valide doit retourner les clés attendues."""
    r = inspecter_tls("google.com")
    assert r is not None
    for cle in ("version", "cipher", "issuer", "subject", "expire_date", "jours_restants"):
        assert cle in r, f"Clé manquante : {cle}"
    assert r["version"] in ("TLSv1.2", "TLSv1.3")
    assert r["jours_restants"] is not None
    assert r["jours_restants"] > 0, "Le certificat de google.com ne doit pas être expiré"


def test_inspecter_tls_invalide():
    """inspecter_tls() sur un hôte inexistant doit retourner None."""
    r = inspecter_tls("hote.inexistant.invalid")
    assert r is None


def test_charger_baseline(tmp_path):
    """charger_baseline() doit parser les valeurs numériques et extraire la date du nom."""
    csv_path = tmp_path / "resultats_20260420_143200.csv"
    csv_path.write_text(
        "url,p50,p95,p99,dns_moyenne,ttfb_p50\n"
        "https://example.com,38.0,145.0,200.0,8.2,28.3\n"
    )
    b = charger_baseline(str(csv_path))
    assert "https://example.com" in b
    entry = b["https://example.com"]
    assert entry["p50"] == 38.0
    assert entry["p95"] == 145.0
    assert entry["dns_moyenne"] == 8.2
    assert entry["ttfb_p50"] == 28.3
    assert entry["date"].startswith("2026-04-20 14:32")


def test_charger_baseline_fichier_absent():
    """charger_baseline() doit lever FileNotFoundError si le fichier est absent."""
    with pytest.raises(FileNotFoundError):
        charger_baseline("/tmp/inexistant_ltiprobe_test.csv")


def test_comparer_baseline_regression():
    """Une hausse ≥ 10% doit être classée régression."""
    resultat = {"p50": 89.0, "p95": 152.0, "p99": 200.0, "dns_moyenne": 8.0, "ttfb_p50": None}
    baseline = {"p50": 38.0, "p95": 145.0, "p99": 190.0, "dns_moyenne": 8.5, "ttfb_p50": None}
    cmp = comparer_baseline(resultat, baseline)
    noms = {c["nom"]: c for c in cmp}
    assert noms["HTTP p50"]["statut"] == "regression"
    assert noms["HTTP p50"]["delta_pct"] == 134
    assert noms["HTTP p95"]["statut"] == "stable"


def test_comparer_baseline_amelioration():
    """Une baisse doit être classée amélioration."""
    resultat = {"p50": 30.0, "p95": None, "p99": None, "dns_moyenne": None, "ttfb_p50": None}
    baseline = {"p50": 38.0, "p95": None, "p99": None, "dns_moyenne": None, "ttfb_p50": None}
    cmp = comparer_baseline(resultat, baseline)
    assert cmp[0]["statut"] == "amelioration"
    assert cmp[0]["delta_pct"] == -21


def test_comparer_baseline_metrique_absente():
    """Une métrique absente dans baseline ou résultat doit être ignorée."""
    resultat = {"p50": 38.0, "p95": None, "p99": None, "dns_moyenne": None, "ttfb_p50": None}
    baseline = {"p50": None, "p95": None, "p99": None, "dns_moyenne": None, "ttfb_p50": None}
    cmp = comparer_baseline(resultat, baseline)
    assert cmp == []


def test_charger_baseline_multi_lignes(tmp_path):
    """Plusieurs lignes pour une même URL → médiane par colonne."""
    csv_path = tmp_path / "resultats_20260420_143200.csv"
    csv_path.write_text(
        "url,p50,p95,p99,dns_moyenne,ttfb_p50\n"
        "https://example.com,30.0,100.0,200.0,8.0,20.0\n"
        "https://example.com,40.0,120.0,220.0,9.0,25.0\n"
        "https://example.com,50.0,110.0,210.0,7.0,30.0\n"
    )
    b = charger_baseline(str(csv_path))
    entry = b["https://example.com"]
    # médiane de [30, 40, 50] → 40
    assert entry["p50"] == 40.0
    # médiane de [100, 110, 120] → 110
    assert entry["p95"] == 110.0
    # médiane de [20, 25, 30] → 25
    assert entry["ttfb_p50"] == 25.0


def test_sauvegarder_prometheus(tmp_path):
    """sauvegarder_prometheus() doit écrire un fichier au format Prometheus text valide."""
    hist = creer_histogramme()
    hdr_enregistrer(hist, 42.0)
    stats = hdr_stats(hist)
    resultats = [{
        "url": "https://example.com",
        "erreur": False,
        "dns_moyenne": 8.5,
        "ttfb_p50": 20.0,
        "transfert_p50": 22.0,
        "icmp_ms": 12.0,
        "tcp_ms": 18.0,
        "tls_ms": 35.0,
        "stabilite_ratio": 1.5,
        "slo_checks": {
            "http_p50_ms": {"seuil": 100, "valeur": 42.0, "ok": True},
        },
        **stats,
    }]
    fichier = str(tmp_path / "metrics.prom")
    sauvegarder_prometheus(resultats, fichier)
    assert os.path.exists(fichier)
    contenu = open(fichier).read()
    assert "# HELP ltiprobe_http_p50_ms" in contenu
    assert "# TYPE ltiprobe_http_p50_ms gauge" in contenu
    assert 'ltiprobe_http_p50_ms{url="https://example.com"}' in contenu
    assert "# HELP ltiprobe_slo_ok" in contenu
    assert 'ltiprobe_slo_ok{url="https://example.com", slo="http_p50_ms"} 1.0' in contenu
    assert 'ltiprobe_dns_moyenne_ms{url="https://example.com"} 8.5' in contenu
    assert contenu.endswith("\n")


def test_sauvegarder_prometheus_erreur_ignoree(tmp_path):
    """sauvegarder_prometheus() doit ignorer les résultats en erreur."""
    resultats = [{"url": "https://bad.com", "erreur": True}]
    fichier = str(tmp_path / "empty.prom")
    sauvegarder_prometheus(resultats, fichier)
    assert os.path.exists(fichier)
    contenu = open(fichier).read()
    assert "bad.com" not in contenu


def test_sauvegarder_csv_comparaison(tmp_path):
    """Le CSV de comparaison doit contenir les colonnes et valeurs attendues."""
    resultats = [{
        "url": "https://example.com",
        "erreur": False,
        "baseline_comparaison": {
            "date": "2026-04-20",
            "lignes": [
                {"nom": "HTTP p50", "cle_csv": "http_p50",
                 "avant": 38.0, "apres": 89.0, "delta_pct": 134, "statut": "regression"},
                {"nom": "DNS", "cle_csv": "dns",
                 "avant": 8.2, "apres": 7.1, "delta_pct": -13, "statut": "amelioration"},
            ],
        },
    }]
    fichier = sauvegarder_csv_comparaison(resultats, str(tmp_path / "cmp.csv"))
    assert os.path.exists(fichier)
    with open(fichier) as f:
        contenu = f.read()
    assert "http_p50_avant" in contenu
    assert "http_p50_statut" in contenu
    assert "regression" in contenu
    assert "amelioration" in contenu
    assert "2026-04-20" in contenu
