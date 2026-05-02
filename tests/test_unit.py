# -*- coding: utf-8 -*-
"""
Unit tests — no real network calls, runs in ~3 s.

All tests here use only pure logic, tmp_path fixtures, or mocked network calls.
Run with:  pytest tests/test_unit.py
"""
import os
import pytest
from ltiprobe.core import (
    sauvegarder_csv,
    sauvegarder_prometheus,
    envoyer_webhook,
    calculer_mos,
    creer_histogramme,
    hdr_enregistrer,
    hdr_stats,
    verifier_slo,
    charger_baseline,
    comparer_baseline,
    sauvegarder_csv_comparaison,
    merger_histogrammes,
)
from ltiprobe.i18n import get_translator


# ── i18n ──────────────────────────────────────────────────────────────────────

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

def test_i18n_es_header():
    """Le traducteur ES doit produire un message en espagnol."""
    t = get_translator("ES")
    assert "intentos" in t("header", ver="0.3.0", n=5, cfg="ltiprobe.yaml")

def test_i18n_de_header():
    """Le traducteur DE doit produire un message en allemand."""
    t = get_translator("DE")
    assert "Versuche" in t("header", ver="0.3.0", n=5, cfg="ltiprobe.yaml")

def test_i18n_ja_header():
    """Le traducteur JA doit produire un message en japonais."""
    t = get_translator("JA")
    assert "測定中" in t("header", ver="0.3.0", n=5, cfg="ltiprobe.yaml")

def test_i18n_zh_header():
    """Le traducteur ZH doit produire un message en chinois simplifié."""
    t = get_translator("ZH")
    assert "测量" in t("header", ver="0.3.0", n=5, cfg="ltiprobe.yaml")

def test_i18n_pt_header():
    """Le traducteur PT doit produire un message en portugais brésilien."""
    t = get_translator("PT")
    assert "tentativas" in t("header", ver="0.3.0", n=5, cfg="ltiprobe.yaml")

def test_i18n_cles_identiques():
    """Toutes les langues doivent avoir exactement les mêmes clés."""
    from ltiprobe.i18n import _TRANSLATIONS
    cles_fr = set(_TRANSLATIONS["FR"].keys())
    for lang in ("EN", "ES", "DE", "JA", "ZH", "PT"):
        assert cles_fr == set(_TRANSLATIONS[lang].keys()), f"Clés manquantes ou en trop pour {lang}"


# ── HDR Histogram ─────────────────────────────────────────────────────────────

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


# ── SLO verification ──────────────────────────────────────────────────────────

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

def test_verifier_slo_stability_ratio():
    """stability_ratio doit vérifier p99/p50 par rapport au seuil."""
    resultat = {"p50": 100.0, "p99": 200.0, "stability_ratio": 2.0}
    checks = verifier_slo(resultat, {"stability_ratio": 3.0})
    assert checks["stability_ratio"]["ok"]
    checks2 = verifier_slo(resultat, {"stability_ratio": 1.5})
    assert not checks2["stability_ratio"]["ok"]

def test_verifier_slo_nouvelles_cles():
    """icmp_ms, tcp_ms, tls_ms et http_keepalive_ms doivent être vérifiables."""
    resultat = {
        "icmp_ms": 12.0, "tcp_ms": 18.0,
        "tls_ms": 45.0, "http_keepalive_ms": 70.0,
    }
    slo = {"icmp_ms": 20, "tcp_ms": 30, "tls_ms": 50, "http_keepalive_ms": 100}
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


# ── Config / YAML loading ─────────────────────────────────────────────────────

def test_config_yaml(tmp_path):
    """config.charger() doit lire nb_measures et timeout correctement."""
    from ltiprobe import config as _config
    yaml_content = "nb_measures: 5\ntimeout: 3\nlanguage: EN\n"
    config_file = tmp_path / "ltiprobe.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")
    data = _config.charger(str(config_file))
    assert data["nb_measures"] == 5
    assert data["timeout"] == 3
    assert data["language"] == "EN"

def test_config_yaml_backward_compat(tmp_path):
    """config.charger() doit accepter les anciennes clés nb_mesures et langue."""
    from ltiprobe import config as _config
    yaml_content = "nb_mesures: 7\nlangue: FR\n"
    config_file = tmp_path / "ltiprobe.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")
    data = _config.charger(str(config_file))
    assert data["nb_measures"] == 7
    assert data["language"] == "FR"


_CLES_SLO_VALIDES = {
    "http_p50_ms", "http_p75_ms", "http_p90_ms",
    "http_p95_ms", "http_p99_ms", "http_p999_ms", "http_max_ms",
    "dns_ms", "stability_ratio", "icmp_ms", "icmp_jitter_ms", "icmp_loss_pct",
    "tcp_ms", "tcp_jitter_ms", "tls_ms",
    "http_keepalive_ms", "nb_hops_max", "mos_min",
}

def test_ltiprobe_yaml_existe():
    """ltiprobe.yaml must exist at the project root."""
    assert os.path.exists("ltiprobe.yaml"), "ltiprobe.yaml not found at project root"

def test_ltiprobe_yaml_structure():
    """ltiprobe.yaml must contain the required tool-config keys with correct types."""
    from ltiprobe import config as _config
    data = _config.charger("ltiprobe.yaml")
    assert isinstance(data.get("nb_measures"), int), "nb_measures must be an integer"
    assert data["nb_measures"] > 0, "nb_measures must be > 0"
    assert isinstance(data.get("timeout"), int), "timeout must be an integer"
    assert data["timeout"] > 0, "timeout must be > 0"
    assert isinstance(data.get("language"), str), "language must be a string"

def test_sites_yaml_existe():
    """sites.yaml must exist at the project root."""
    assert os.path.exists("sites.yaml"), "sites.yaml not found at project root"

def test_sites_yaml_structure():
    """sites.yaml must be a non-empty list of dicts with valid URLs."""
    from ltiprobe import config as _config
    sites = _config.charger_sites("sites.yaml")
    assert isinstance(sites, list), "sites.yaml must be a YAML list"
    assert len(sites) > 0, "sites.yaml must not be empty"
    for site in sites:
        assert "url" in site, f"Entry missing 'url' key: {site}"
        url = site["url"]
        assert url.startswith("http://") or url.startswith("https://"), \
            f"Invalid URL (must start with http:// or https://): {url}"

def test_sites_yaml_slo_cles():
    """SLO keys in sites.yaml must be recognised by verifier_slo."""
    from ltiprobe import config as _config
    sites = _config.charger_sites("sites.yaml")
    for site in sites:
        slo = site.get("slo")
        if not slo:
            continue
        unknown = set(slo.keys()) - _CLES_SLO_VALIDES
        assert not unknown, f"Unknown SLO keys for {site['url']}: {unknown}"
        for key, value in slo.items():
            assert isinstance(value, (int, float)) and value > 0, \
                f"Invalid SLO threshold for {site['url']}.{key}: {value}"

def test_charger_sites_liste_directe(tmp_path):
    """charger_sites() must parse a direct YAML list."""
    from ltiprobe import config as _config
    f = tmp_path / "sites.yaml"
    f.write_text("- url: https://example.com\n- url: https://test.com\n", encoding="utf-8")
    sites = _config.charger_sites(str(f))
    assert len(sites) == 2
    assert sites[0]["url"] == "https://example.com"

def test_charger_sites_fichier_absent():
    """charger_sites() with no explicit path returns [] if sites.yaml is absent."""
    from ltiprobe import config as _config
    import unittest.mock as mock
    with mock.patch("os.path.exists", return_value=False):
        assert _config.charger_sites() == []

def test_charger_sites_fichier_explicite_absent(tmp_path):
    """charger_sites() raises FileNotFoundError for an explicit missing file."""
    from ltiprobe import config as _config
    with pytest.raises(FileNotFoundError):
        _config.charger_sites(str(tmp_path / "inexistant.yaml"))

def test_charger_sites_format_invalide(tmp_path):
    """charger_sites() raises ValueError if the file is not a YAML list."""
    from ltiprobe import config as _config
    f = tmp_path / "bad.yaml"
    f.write_text("sites:\n  - url: https://example.com\n", encoding="utf-8")
    with pytest.raises(ValueError):
        _config.charger_sites(str(f))


# ── MOS calculation ───────────────────────────────────────────────────────────

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


# ── Jitter ────────────────────────────────────────────────────────────────────

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


# ── est_adresse_ip ────────────────────────────────────────────────────────────

def test_est_adresse_ip():
    """est_adresse_ip doit distinguer IP et nom de domaine."""
    from ltiprobe.core import est_adresse_ip
    assert est_adresse_ip("8.8.8.8")
    assert est_adresse_ip("2001:4860:4860::8888")  # IPv6
    assert not est_adresse_ip("google.com")
    assert not est_adresse_ip("192.168.x.x")  # invalide


# ── CSV / Export ──────────────────────────────────────────────────────────────

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
        "stability_ratio": 1.5,
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


# ── merger_histogrammes ───────────────────────────────────────────────────────

def _csv_avec_histogramme(path, url, valeurs_ms):
    """Crée un CSV minimal avec hdr_encode pour les valeurs données (en ms)."""
    hist = creer_histogramme()
    for v in valeurs_ms:
        hist.record_value(int(v * 1000))
    encoded = hist.encode()
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("url,p50,p99,hdr_encode\n")
        f.write(f'"{url}",0,0,"{repr(encoded)}"\n')


def test_merger_histogrammes_structure(tmp_path):
    """merger_histogrammes doit retourner un dict avec les bonnes clés."""
    f1 = tmp_path / "a.csv"
    _csv_avec_histogramme(str(f1), "https://example.com", [50, 60, 70])
    result = merger_histogrammes([str(f1)])
    assert result is not None
    assert "https://example.com" in result
    data = result["https://example.com"]
    assert "sources" in data
    assert "merged" in data
    assert "nb_total" in data
    assert data["nb_total"] == 3


def test_merger_histogrammes_deux_fichiers(tmp_path):
    """Deux fichiers CSV pour le même URL doivent être fusionnés correctement."""
    f1 = tmp_path / "a.csv"
    f2 = tmp_path / "b.csv"
    _csv_avec_histogramme(str(f1), "https://example.com", [50] * 100)
    _csv_avec_histogramme(str(f2), "https://example.com", [100] * 100)
    result = merger_histogrammes([str(f1), str(f2)])
    assert result is not None
    data = result["https://example.com"]
    assert data["nb_total"] == 200
    assert len(data["sources"]) == 2
    merged = data["merged"]
    assert merged["p50"] is not None
    assert merged["p99"] is not None


def test_merger_histogrammes_plusieurs_urls(tmp_path):
    """Deux URLs distincts dans les fichiers produisent deux entrées dans le résultat."""
    f1 = tmp_path / "a.csv"
    f2 = tmp_path / "b.csv"
    _csv_avec_histogramme(str(f1), "https://alpha.com", [30, 40])
    _csv_avec_histogramme(str(f2), "https://beta.com", [80, 90])
    result = merger_histogrammes([str(f1), str(f2)])
    assert result is not None
    assert "https://alpha.com" in result
    assert "https://beta.com" in result


def test_merger_histogrammes_fichier_absent(tmp_path):
    """Un fichier inexistant est ignoré sans lever d'exception."""
    f1 = tmp_path / "real.csv"
    _csv_avec_histogramme(str(f1), "https://example.com", [50])
    result = merger_histogrammes([str(f1), str(tmp_path / "inexistant.csv")])
    assert result is not None
    assert "https://example.com" in result


def test_merger_histogrammes_sans_hdr_encode(tmp_path):
    """Un CSV sans colonne hdr_encode retourne None."""
    f1 = tmp_path / "no_hist.csv"
    with open(str(f1), "w", encoding="utf-8") as f:
        f.write("url,p50,p99\n")
        f.write("https://example.com,50,100\n")
    result = merger_histogrammes([str(f1)])
    assert result is None


# ── N : http_max_ms dans le système SLO ──────────────────────────────────────

def test_slo_http_max_ms():
    """http_max_ms doit être accepté comme clé SLO valide."""
    from ltiprobe.core import _SLO_VERS_RESULTAT
    assert "http_max_ms" in _SLO_VERS_RESULTAT
    assert _SLO_VERS_RESULTAT["http_max_ms"] == "max"


def test_verifier_slo_http_max_ms_ok():
    """http_max_ms : pas de violation si max < seuil."""
    resultat = {"p50": 20.0, "p99": 80.0, "max": 150.0,
                "dns_moyenne": 5.0, "stability_ratio": 3.0,
                "icmp_ms": None, "icmp_jitter_ms": None, "icmp_loss_pct": None,
                "tcp_ms": None, "tcp_jitter_ms": None, "tls_ms": None,
                "mos": None, "http_keepalive_ms": None, "nb_hops": None,
                "p75": 50.0, "p90": 70.0, "p95": 75.0, "p999": 120.0}
    slo = {"http_max_ms": 200}
    checks = verifier_slo(resultat, slo)
    assert checks["http_max_ms"]["ok"] is True


def test_verifier_slo_http_max_ms_violation():
    """http_max_ms : violation si max > seuil."""
    resultat = {"p50": 20.0, "p99": 80.0, "max": 500.0,
                "dns_moyenne": 5.0, "stability_ratio": 3.0,
                "icmp_ms": None, "icmp_jitter_ms": None, "icmp_loss_pct": None,
                "tcp_ms": None, "tcp_jitter_ms": None, "tls_ms": None,
                "mos": None, "http_keepalive_ms": None, "nb_hops": None,
                "p75": 50.0, "p90": 70.0, "p95": 75.0, "p999": 120.0}
    slo = {"http_max_ms": 200}
    checks = verifier_slo(resultat, slo)
    assert checks["http_max_ms"]["ok"] is False


# ── Q : calcul de la probabilité compound latency ────────────────────────────

def test_impact_compound_p50():
    """P(≥1 sur N ressources dépasse P50) = 1 - 0.5^N."""
    n = 10
    p_ok = 0.50
    prob = (1.0 - p_ok ** n) * 100.0
    assert abs(prob - (1 - 0.5 ** 10) * 100) < 0.001


def test_impact_compound_p99_40_ressources():
    """Avec 40 ressources et P99, ~33% de probabilité d'au moins 1 dépassement."""
    n = 40
    p_ok = 0.99
    prob = (1.0 - p_ok ** n) * 100.0
    assert 32 < prob < 34


def test_impact_compound_p999_40_ressources():
    """Avec 40 ressources et P99.9, ~3.9% de probabilité."""
    n = 40
    p_ok = 0.999
    prob = (1.0 - p_ok ** n) * 100.0
    assert 3 < prob < 5


# ── R : traduction percentiles → utilisateurs/heure ──────────────────────────

def test_impact_users_p99():
    """P99 avec 10 000 req/h → ~100 utilisateurs affectés."""
    req = 10_000
    pct = 99.0
    n_aff = max(1, round((100.0 - pct) / 100.0 * req))
    assert n_aff == 100


def test_impact_users_p999():
    """P99.9 avec 10 000 req/h → ~10 utilisateurs affectés."""
    req = 10_000
    pct = 99.9
    n_aff = max(1, round((100.0 - pct) / 100.0 * req))
    assert n_aff == 10
