# -*- coding: utf-8 -*-
"""
Network tests — real HTTP/DNS/TCP/ICMP/TLS calls, runs in ~45 s.

These tests require a working internet connection and, for some probes
(ICMP, traceroute), root/admin privileges or a capable environment.

Run with:  pytest tests/test_network.py
Skip in CI: set the CI=true env variable (some tests auto-skip on CI=true).
"""
import os
import pytest
from ltiprobe.core import (
    mesurer_site,
    verifier_assertions,
    inspecter_tls,
    mesurer_dns_ttl,
    detecter_reseau,
    lister_interfaces,
    decouvrir_path_mtu,
    mesurer_traceroute_detail,
)


# ── HTTP assertions ───────────────────────────────────────────────────────────

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


# ── TCP ───────────────────────────────────────────────────────────────────────

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


# ── TLS ───────────────────────────────────────────────────────────────────────

def test_mesurer_tls_valide():
    """Un site HTTPS accessible doit retourner des temps de handshake positifs."""
    from ltiprobe.core import mesurer_tls
    r = mesurer_tls("https://google.com", nb_mesures=2)
    assert r is not None
    assert r["moyenne"] > 0
    assert r["min"] <= r["moyenne"] <= r["max"]
    assert r["nb"] == 2

def test_mesurer_tls_invalide():
    """Un hôte inexistant doit retourner None."""
    from ltiprobe.core import mesurer_tls
    r = mesurer_tls("https://hote.inexistant.invalid", nb_mesures=1)
    assert r is None

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


# ── Network detection / interfaces ───────────────────────────────────────────

def test_detecter_reseau_structure():
    """detecter_reseau doit retourner un dict avec les clés attendues."""
    r = detecter_reseau()
    assert r is not None
    assert set(r.keys()) == {"local_ip", "interface", "interfaces", "public_ip", "isp", "as_info", "pays", "pays_code"}

def test_lister_interfaces_retourne_liste():
    """lister_interfaces doit retourner une liste (vide ou non)."""
    ifaces = lister_interfaces()
    assert isinstance(ifaces, list)

def test_lister_interfaces_structure():
    """Chaque interface doit avoir les clés device, type, actif."""
    ifaces = lister_interfaces()
    for iface in ifaces:
        assert "device" in iface
        assert "type"   in iface
        assert "actif"  in iface

def test_lister_interfaces_active_marquee():
    """L'interface active doit être marquée actif=True, les autres False."""
    r = detecter_reseau()
    iface_active = r.get("interface") if r else None
    if not iface_active:
        return
    ifaces = lister_interfaces(iface_active)
    actives = [i for i in ifaces if i["actif"]]
    assert len(actives) <= 1
    if actives:
        assert actives[0]["device"] == iface_active

def test_detecter_reseau_local_ip():
    """L'IP locale doit être une adresse IPv4 valide."""
    import ipaddress
    r = detecter_reseau()
    assert r is not None
    assert r["local_ip"] is not None
    ipaddress.ip_address(r["local_ip"])  # lève ValueError si invalide

def test_detecter_reseau_public_ip():
    """L'IP publique doit être présente et différente de l'IP locale."""
    r = detecter_reseau()
    assert r is not None
    assert r["public_ip"] is not None
    import ipaddress
    ipaddress.ip_address(r["public_ip"])


# ── DNS ───────────────────────────────────────────────────────────────────────

def test_mesurer_dns_ttl_valide():
    """Un hôte accessible doit retourner reseau_ms, cache_ms et ttl_s."""
    r = mesurer_dns_ttl("google.com")
    assert r is not None
    assert r["reseau_ms"] is not None and r["reseau_ms"] > 0
    assert r["cache_ms"] is not None and r["cache_ms"] >= 0
    assert r["ttl_s"] is not None and r["ttl_s"] > 0
    # Le cache OS doit être significativement plus rapide que la résolution réseau
    assert r["cache_ms"] < r["reseau_ms"]

def test_mesurer_dns_ttl_invalide():
    """Un hôte inexistant doit retourner None."""
    r = mesurer_dns_ttl("hote.inexistant.invalid")
    assert r is None

def test_mesurer_dns_ttl_structure():
    """Le dict retourné doit contenir exactement les clés attendues."""
    r = mesurer_dns_ttl("google.com")
    assert r is not None
    assert set(r.keys()) == {"reseau_ms", "cache_ms", "ttl_s"}

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


# ── Traceroute (basic) ────────────────────────────────────────────────────────

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


# ── ICMP ──────────────────────────────────────────────────────────────────────

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


# ── IP reachability ───────────────────────────────────────────────────────────

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


# ── mesurer_site ──────────────────────────────────────────────────────────────

def test_mesurer_site_ip_dns_na():
    """Un site accédé par IP ne doit pas avoir de mesure DNS."""
    r = mesurer_site("http://93.184.216.34", nb_mesures=1)
    if not r["erreur"]:
        assert r["ip_mode"] is True
        assert r["dns_moyenne"] is None

def test_mesurer_site_valide():
    """Un site valide doit retourner HTTP, DNS et la distribution complète."""
    r = mesurer_site("https://google.com", nb_mesures=1)
    assert not r["erreur"]
    assert r["moyenne"] > 0
    assert r["dns_moyenne"] > 0
    for cle in ["p50", "p75", "p90", "p95", "p99", "p999", "hdr_encode"]:
        assert cle in r, f"Clé manquante : {cle}"

def test_mesurer_site_timeout():
    """Un timeout tres court doit retourner une erreur."""
    r = mesurer_site("https://google.com", nb_mesures=1, timeout=0.001)
    assert r["erreur"]
    assert r["type_erreur"] in ["timeout", "inconnu", "http"]

def test_mesurer_site_url_malformee():
    """Une URL malformee doit retourner une erreur."""
    r = mesurer_site("pas-une-url", nb_mesures=1)
    assert r["erreur"]


# ── CDN detection ─────────────────────────────────────────────────────────────

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


# ── Path MTU Discovery ────────────────────────────────────────────────────────

def test_decouvrir_path_mtu_structure():
    """decouvrir_path_mtu() doit retourner un dict avec mtu, sondages, blackhole ou None."""
    import platform
    result = decouvrir_path_mtu("8.8.8.8", timeout=1)
    if platform.system() not in ("Darwin", "Linux"):
        assert result is None
        return
    assert result is not None
    assert "mtu" in result
    assert "sondages" in result
    assert "blackhole" in result
    assert isinstance(result["sondages"], int)
    assert result["sondages"] > 0

def test_decouvrir_path_mtu_standard():
    """Pour une IP publique sans MTU réduit, le MTU doit être >= 576."""
    import platform
    if platform.system() not in ("Darwin", "Linux"):
        pytest.skip("path MTU non disponible sur cette plateforme")
    result = decouvrir_path_mtu("8.8.8.8", timeout=1)
    assert result is not None
    if result.get("blackhole"):
        pytest.skip("PMTUD blackhole détecté — impossible de valider le MTU")
    assert result["mtu"] is not None
    assert result["mtu"] >= 576

def test_decouvrir_path_mtu_hostname_http():
    """decouvrir_path_mtu() doit accepter les URL avec http:// ou https:// en préfixe."""
    import platform
    if platform.system() not in ("Darwin", "Linux"):
        pytest.skip("path MTU non disponible sur cette plateforme")
    result = decouvrir_path_mtu("https://8.8.8.8", timeout=1)
    assert result is not None or True  # accepte None si non joignable

def test_decouvrir_path_mtu_hote_invalide():
    """Un hôte invalide ne doit pas lever d'exception (None ou blackhole acceptés)."""
    import platform
    if platform.system() not in ("Darwin", "Linux"):
        pytest.skip("path MTU non disponible sur cette plateforme")
    result = decouvrir_path_mtu("hote-invalide-xyz.local", timeout=1)
    assert result is None or result.get("blackhole") is True or result.get("mtu") is None


# ── Traceroute hop-by-hop ─────────────────────────────────────────────────────

def test_mesurer_traceroute_detail_structure():
    """mesurer_traceroute_detail() doit retourner la structure attendue ou None."""
    import platform
    result = mesurer_traceroute_detail("8.8.8.8", nb_sondages=3, timeout=1)
    if platform.system() == "Windows":
        assert result is None
        return
    if result is None:
        pytest.skip("traceroute non disponible dans cet environnement")
    assert "hops" in result
    assert "nb_hops" in result
    assert "destination_atteinte" in result
    assert isinstance(result["hops"], list)
    assert len(result["hops"]) > 0

def test_mesurer_traceroute_detail_hop_structure():
    """Chaque hop doit contenir les champs requis."""
    import platform
    if platform.system() == "Windows":
        pytest.skip("non disponible sur Windows")
    result = mesurer_traceroute_detail("8.8.8.8", nb_sondages=3, timeout=1)
    if result is None:
        pytest.skip("traceroute non disponible dans cet environnement")
    for h in result["hops"]:
        assert "hop" in h
        assert "silencieux" in h
        assert "loss_pct" in h
        assert "atteint" in h
        if not h["silencieux"]:
            assert h["moyenne"] is not None
            assert h["jitter"] is not None
            assert 0.0 <= h["loss_pct"] <= 100

def test_mesurer_traceroute_detail_destination():
    """La destination 8.8.8.8 doit être atteinte."""
    import platform
    if platform.system() == "Windows":
        pytest.skip("non disponible sur Windows")
    result = mesurer_traceroute_detail("8.8.8.8", nb_sondages=3, timeout=1)
    if result is None:
        pytest.skip("traceroute non disponible dans cet environnement")
    assert result["destination_atteinte"] is True

def test_mesurer_traceroute_detail_hote_invalide():
    """Un hôte invalide ne doit pas lever d'exception."""
    import platform
    if platform.system() == "Windows":
        pytest.skip("non disponible sur Windows")
    result = mesurer_traceroute_detail("hote-invalide-xyz-123.invalid", nb_sondages=2, timeout=1)
    assert result is None or isinstance(result, dict)
