# -*- coding: utf-8 -*-
import argparse
import sys
import time
import threading
from datetime import datetime, timezone
from tqdm import tqdm
from ltiprobe import config, __version__
from ltiprobe.i18n import get_translator
from hdrh.histogram import HdrHistogram as _HdrHistogram
from ltiprobe.core import (
    mesurer_site, sauvegarder_csv, sauvegarder_prometheus, envoyer_webhook,
    creer_histogramme, hdr_enregistrer, hdr_stats,
    verifier_slo, verifier_assertions,
    mesurer_icmp, mesurer_tcp, mesurer_tls, mesurer_traceroute, inspecter_tls,
    detecter_cdn, est_adresse_ip, verifier_ip_joignable,
    charger_baseline, comparer_baseline, sauvegarder_csv_comparaison,
    calculer_mos, mesurer_dns_ttl, detecter_reseau, decouvrir_path_mtu,
    mesurer_traceroute_detail, merger_histogrammes,
    SLO_UNITES, _SEUIL_EXPIRY_ALERTE,
)

# Codes ANSI — désactivés si la sortie n'est pas un terminal (fichier, CI)
def _ansi(code):
    return "\033[" + code + "m" if sys.stdout.isatty() else ""

VERT   = _ansi("92")
ORANGE = _ansi("33")
ROUGE  = _ansi("91")
RESET  = _ansi("0")

# Traducteur — initialisé dans main() après chargement du fichier de config
t = get_translator(config.LANGUE)

# Seuil de détection de dégradation : +50% par rapport à l'itération précédente
SEUIL_DEGRADATION = 0.50

def _heure_scan():
    """Retourne l'heure locale avec timezone et l'équivalent UTC."""
    local = datetime.now().astimezone()
    utc   = datetime.now(timezone.utc)
    return f"{local.strftime('%H:%M')} {local.strftime('%Z')} / {utc.strftime('%H:%M')} UTC"

def _heure_locale():
    """Retourne l'heure locale avec abréviation de timezone (pour les alertes)."""
    local = datetime.now().astimezone()
    return f"{local.strftime('%H:%M')} {local.strftime('%Z')}"

_NOMS_METRIQUES = {
    "p50":         "p50",
    "p95":         "p95",
    "p99":         "p99",
    "dns_moyenne": "dns",
    "icmp_ms":     "icmp",
}

def parse_arguments():
    # Pré-parse pour récupérer --config-file avant de charger la config complète
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config-file", default=None)
    pre_args, _ = pre.parse_known_args()

    cfg = config.charger(pre_args.config_file)

    parser = argparse.ArgumentParser(
        prog="ltiprobe",
        description="HTTP/DNS/ICMP/TCP/TLS latency measurement tool with SLO validation and HDR histograms"
    )
    parser.add_argument("--version", action="version", version=f"ltiprobe {__version__}")
    parser.add_argument(
        "--config-file",
        default=None,
        metavar="FILE",
        help=f"YAML configuration file (default: {config.FICHIER_DEFAUT})"
    )
    parser.add_argument(
        "sites", nargs="*",
        help="Sites to measure (e.g. https://google.com https://github.com)"
    )
    parser.add_argument(
        "-n", "--nombre", type=int, default=cfg["nb_measures"],
        help="Number of measurements per site (default: %(default)s)"
    )
    parser.add_argument(
        "--sites-file", default=None, metavar="FILE",
        help=f"YAML file containing the list of sites to measure (default: {config.FICHIER_SITES_DEFAUT})"
    )
    parser.add_argument("--csv", action="store_true",
        help="Save results to a CSV file")
    parser.add_argument(
        "--timeout", type=int, default=cfg["timeout"],
        help="Timeout in seconds (default: %(default)s)"
    )
    parser.add_argument("--traceroute", action="store_true",
        help="Show network hop count to each site")
    parser.add_argument("--no-verify-tls", action="store_true",
        help="Disable TLS certificate validation (useful for self-signed certs or direct IPs)")
    parser.add_argument(
        "--interval", type=int, default=None, metavar="SECONDS",
        help="Re-run measurements every N seconds (continuous monitoring)"
    )
    parser.add_argument(
        "--baseline", default=None, metavar="FILE",
        help="Reference CSV file to detect performance regressions"
    )
    parser.add_argument(
        "--prometheus-out", default=None, metavar="FILE",
        help="Export metrics in Prometheus text format (e.g. metrics.prom)"
    )
    parser.add_argument("--tls-info", action="store_true",
        help="Show advanced TLS certificate details (version, cipher, expiry, HSTS)")
    parser.add_argument(
        "--verbosity", choices=["basic", "full"], default=cfg.get("verbosity", "full"),
        metavar="LEVEL",
        help="Output detail level: basic (HTTP/DNS/SLO only) or full (all sections, default: %(default)s)"
    )
    parser.add_argument("--path-mtu", action="store_true",
        help="Discover effective Path MTU to each site (binary search via ping -D / -M do)")
    parser.add_argument("--traceroute-detail", action="store_true",
        help="Hop-by-hop analysis with jitter and loss per hop (5 probes/hop, implies --traceroute)")
    parser.add_argument(
        "--merge", nargs="+", metavar="FILE",
        help="Merge HDR histograms from multiple ltiprobe CSV exports and display combined statistics"
    )
    return parser.parse_args(), cfg

# ── Indicateurs colorés ───────────────────────────────────────────────────────

def indicateur_stabilite(p50, p99):
    if p50 <= 0:
        return "n/a"
    ratio = p99 / p50
    ratio_str = t("ratio", r=round(ratio, 1))
    if ratio < 2:
        return VERT   + t("tres_stable") + ratio_str + RESET
    if ratio < 5:
        return VERT   + t("stable")      + ratio_str + RESET
    if ratio < 10:
        return ORANGE + t("variable")    + ratio_str + RESET
    return ROUGE  + t("instable")    + ratio_str + RESET

def indicateur_hops(nb_hops):
    if nb_hops <= 15:
        return VERT   + t("hops_excellent") + RESET
    if nb_hops <= 25:
        return VERT   + t("hops_bon")       + RESET
    if nb_hops <= 35:
        return ORANGE + t("hops_eleve")     + RESET
    return ROUGE  + t("hops_critique")  + RESET

def _delta(a, b):
    if a is None or b is None or a <= 0:
        return ""
    d = round(b - a, 1)
    return ("  (+" + str(d) + " ms)") if d > 0 else ""

# ── Sections d'affichage ──────────────────────────────────────────────────────

def _fmt_ms(v):
    """Formate une valeur ms avec une décimale (ex: 23.4), ou '—' si None."""
    return f"{v:.1f}" if v is not None else "—"

def _fmt_jitter(valeur):
    """Formate le jitter en ms avec une décimale, ou '—' si absent."""
    return f"{valeur:.1f}" if valeur is not None else "—"

def _fmt_loss(pct):
    """Formate le packet loss avec couleur."""
    if pct is None:
        return "—"
    if pct == 0.0:
        return VERT + "0%" + RESET
    return ORANGE + str(pct) + "%" + RESET

def afficher_protocoles(icmp, tcp, tls, http_p50, site):
    port     = tcp["port"] if tcp else 443
    icmp_moy = icmp["moyenne"] if icmp else None
    tcp_moy  = tcp["moyenne"]  if tcp  else None
    tls_moy  = tls["moyenne"]  if tls  else None

    print(t("proto_titre"))
    if icmp:
        print(t("proto_icmp", v=_fmt_ms(icmp_moy), min=_fmt_ms(icmp["min"]), max=_fmt_ms(icmp["max"]),
                jitter=_fmt_jitter(icmp.get("jitter")),
                loss=_fmt_loss(icmp.get("loss_pct")), n=icmp["nb"]))
    else:
        print(t("proto_icmp_na"))

    if tcp:
        print(t("proto_tcp", p=port, v=_fmt_ms(tcp_moy), min=_fmt_ms(tcp["min"]), max=_fmt_ms(tcp["max"]),
                jitter=_fmt_jitter(tcp.get("jitter")))
              + _delta(icmp_moy, tcp_moy))
    else:
        print(t("proto_tcp_na", p=port))

    if tls:
        print(t("proto_tls", v=_fmt_ms(tls_moy), min=_fmt_ms(tls["min"]), max=_fmt_ms(tls["max"]),
                jitter=_fmt_jitter(tls.get("jitter")))
              + _delta(tcp_moy if tcp_moy else icmp_moy, tls_moy))
    elif site.startswith("https://"):
        print(t("proto_tls_na"))

    if http_p50:
        prev = tls_moy or tcp_moy or icmp_moy
        print(t("proto_http_froid", v=_fmt_ms(http_p50)) + _delta(prev, http_p50))
        surcharge = round((tcp_moy or 0) + (tls_moy or 0), 1)
        http_keepalive = round(http_p50 - surcharge, 1)
        if surcharge > 0 and http_keepalive > 0:
            print(t("proto_http_keepalive", v=_fmt_ms(http_keepalive)))

def afficher_traceroute(tr):
    if tr is None:
        print(t("traceroute_na"))
        return
    if not tr["destination_atteinte"]:
        print(t("traceroute_non_atteint", n=tr["nb_hops"]))
        return
    masques = ("  (" + str(tr["nb_masques"]) + " " + t("hops_masques") + ")") if tr["nb_masques"] else ""
    print(t("traceroute_hops", n=tr["nb_hops"])
          + "  " + indicateur_hops(tr["nb_hops"]) + masques)

_SEUIL_JITTER_MS   = 2.0   # au-delà → alerte orange
_SEUIL_LOSS_PCT    = 0     # > 0% → alerte orange

def afficher_traceroute_detail(tr_detail, nb_sondages=5):
    if tr_detail is None:
        print(t("trdetail_na"))
        return
    print(t("trdetail_titre", n=nb_sondages))
    for h in tr_detail["hops"]:
        if h["silencieux"]:
            print(t("trdetail_hop_silencieux", hop=h["hop"]))
            continue
        alertes = []
        if h["jitter"] is not None and h["jitter"] >= _SEUIL_JITTER_MS:
            alertes.append(ORANGE + t("trdetail_alerte_jitter") + RESET)
        if h["loss_pct"] and h["loss_pct"] > _SEUIL_LOSS_PCT:
            alertes.append(ORANGE + t("trdetail_alerte_loss") + RESET)
        loss_str = (ORANGE + str(h["loss_pct"]) + "%" + RESET) if h["loss_pct"] else (VERT + "0%" + RESET)
        ligne = t("trdetail_hop",
                  hop=h["hop"],
                  ip=h["ip"] or "*",
                  moy=_fmt_ms(h["moyenne"]),
                  jitter=_fmt_jitter(h["jitter"]),
                  loss=loss_str)
        if h.get("atteint"):
            ligne = VERT + ligne + RESET
        print(ligne + "".join(alertes))
    if tr_detail["destination_atteinte"]:
        print(VERT + t("trdetail_destination", n=tr_detail["nb_hops"]) + RESET)
    else:
        print(ORANGE + t("trdetail_non_atteint", n=tr_detail["nb_hops"]) + RESET)

def afficher_cdn(cdn_info):
    if cdn_info is None:
        print(t("cdn_erreur"))
        return
    print(t("cdn_titre"))
    cdn_nom = cdn_info.get("cdn") or t("cdn_inconnu")
    cache   = cdn_info.get("cache")
    age_s   = cdn_info.get("age_s")
    pop     = cdn_info.get("pop")

    statut = ""
    if cache == "HIT":
        statut = VERT  + t("cdn_hit")  + RESET
    elif cache == "MISS":
        statut = ORANGE + t("cdn_miss") + RESET

    parties = []
    if pop:
        parties.append(t("cdn_pop", p=pop))
    if age_s is not None:
        parties.append(t("cdn_age", s=age_s))
    suite = "  ".join(parties)

    if not cache and not cdn_info.get("cdn"):
        print(t("cdn_aucun"))
    else:
        print(t("cdn_ligne", statut=statut, cdn=cdn_nom, suite=suite))

def afficher_reseau(info):
    print(t("reseau_titre"))
    if info is None:
        print(t("reseau_na"))
        return
    for iface in info.get("interfaces") or []:
        cle = "reseau_iface_actif" if iface["actif"] else "reseau_iface_autre"
        couleur = VERT if iface["actif"] else ""
        ligne = t(cle, device=iface["device"], type=iface["type"])
        print(couleur + ligne + (RESET if couleur else ""))
    if info.get("local_ip"):
        print(t("reseau_local_ip",  v=info["local_ip"]))
    if info.get("public_ip"):
        print(t("reseau_public_ip", v=info["public_ip"]))
    if info.get("isp"):
        print(t("reseau_isp",       v=info["isp"]))
    if info.get("as_info"):
        print(t("reseau_as",        v=info["as_info"]))
    if info.get("pays") and info.get("pays_code"):
        print(t("reseau_pays",      v=info["pays"], code=info["pays_code"]))

def afficher_dns_ttl(dns_ttl):
    if dns_ttl is None:
        return
    print(t("dns_ttl_titre"))
    if dns_ttl.get("reseau_ms") is not None:
        print(t("dns_ttl_reseau", v=_fmt_ms(dns_ttl["reseau_ms"])))
    if dns_ttl.get("cache_ms") is not None:
        couleur = VERT if (
            dns_ttl.get("reseau_ms") and dns_ttl["cache_ms"] < dns_ttl["reseau_ms"] * 0.3
        ) else RESET
        print(couleur + t("dns_ttl_cache", v=_fmt_ms(dns_ttl["cache_ms"])) + RESET)
    if dns_ttl.get("ttl_s") is not None:
        print(t("dns_ttl_valeur", s=dns_ttl["ttl_s"]))

def afficher_tls_info(tls_info):
    if tls_info is None:
        print(t("tls_info_na"))
        return
    print(t("tls_info_titre"))
    print(t("tls_version", v=tls_info["version"]))
    print(t("tls_cipher",  v=tls_info["cipher"]))
    print(t("tls_issuer",  v=tls_info["issuer"]))
    print(t("tls_subject", v=tls_info["subject"]))

    jours = tls_info.get("jours_restants")
    expire = tls_info.get("expire_date")
    if expire is not None and jours is not None:
        date_str = expire.strftime("%Y-%m-%d")
        if jours < 0:
            statut = ROUGE + t("tls_expire_expiré") + RESET
        elif jours <= _SEUIL_EXPIRY_ALERTE:
            statut = ORANGE + t("tls_expire_alerte", j=jours) + RESET
        else:
            statut = VERT + t("tls_expire_ok", j=jours) + RESET
        print(t("tls_expiry", date=date_str, statut=statut))

    hsts = tls_info.get("hsts")
    if hsts:
        print(t("tls_hsts", v=hsts))
    else:
        print(t("tls_hsts_absent"))

def afficher_scoring_standards(icmp_ms, icmp_jitter_ms, icmp_loss_pct):
    """Affiche la section Scoring Standards avec le MOS ITU-T G.107."""
    mos_data = calculer_mos(icmp_ms, icmp_jitter_ms or 0.0, icmp_loss_pct or 0.0)
    mos  = mos_data["mos"]
    r    = mos_data["r_factor"]
    qual = mos_data["qualite"]

    if mos >= 4.0:
        couleur = VERT
        statut  = "✓"
    elif mos >= 3.6:
        couleur = ORANGE
        statut  = "~"
    else:
        couleur = ROUGE
        statut  = "✗"

    qualite_str = couleur + t("mos_" + qual) + RESET

    print(t("scoring_titre"))
    print(t("scoring_mos_titre"))
    print(t("scoring_r_factor", v=r))
    print(t("scoring_mos", v=mos, statut=couleur + statut + RESET, qualite=qualite_str))

def afficher_path_mtu(pmtu):
    print(t("path_mtu_titre"))
    if pmtu is None:
        print(t("path_mtu_na"))
        return
    if pmtu.get("blackhole"):
        print(ROUGE + t("path_mtu_blackhole") + RESET)
        print(t("path_mtu_sondages", n=pmtu["sondages"]))
        return
    mtu = pmtu.get("mtu")
    if mtu is None:
        print(t("path_mtu_na"))
        return
    if mtu >= 1480:
        couleur = VERT
        qualite = t("path_mtu_standard")
    elif mtu >= 1400:
        couleur = ORANGE
        qualite = t("path_mtu_reduit")
    else:
        couleur = ROUGE
        qualite = t("path_mtu_minimal")
    print(couleur + t("path_mtu_valeur", v=mtu, qualite=qualite) + RESET)
    print(t("path_mtu_sondages", n=pmtu["sondages"]))

def afficher_merge(resultats):
    import os
    if not resultats:
        print(t("merge_na"))
        return
    for url, data in resultats.items():
        sources = data["sources"]
        merged  = data["merged"]
        print(t("merge_titre", n=len(sources)))
        print(f"  {url}")
        for s in sources:
            fname = os.path.basename(s["fichier"])
            print(t("merge_source", f=fname, nb=s["nb"], p50=_fmt_ms(s["p50"]), p99=_fmt_ms(s["p99"])))
        print("  " + "─" * 60)
        print(t("merge_global", nb=data["nb_total"], p50=_fmt_ms(merged["p50"]), p99=_fmt_ms(merged["p99"])))

def afficher_impact_utilisateur(r, nb_ressources, req_par_heure):
    """Q + R — Traduit les percentiles en impact utilisateur concret."""
    if not nb_ressources and not req_par_heure:
        return
    print(t("impact_titre"))
    stats = [
        ("P50",   r.get("p50"),  50.0),
        ("P99",   r.get("p99"),  99.0),
        ("P99.9", r.get("p999"), 99.9),
    ]
    if nb_ressources:
        print(t("impact_ressources_titre", n=nb_ressources))
        for label, ms, pct in stats:
            if ms is None:
                continue
            prob = (1.0 - (pct / 100.0) ** nb_ressources) * 100.0
            couleur = ROUGE if prob >= 50 else (ORANGE if prob >= 10 else VERT)
            print(couleur + t("impact_ressources_ligne",
                               label=label, ms=_fmt_ms(ms),
                               prob=f"{prob:.1f}%") + RESET)
    if req_par_heure:
        print(t("impact_users_titre", n=req_par_heure))
        for label, ms, pct in stats:
            if ms is None:
                continue
            n_aff = max(1, round((100.0 - pct) / 100.0 * req_par_heure))
            couleur = ROUGE if n_aff >= req_par_heure * 0.01 else VERT
            print(couleur + t("impact_users_ligne",
                               label=label, ms=_fmt_ms(ms), n=n_aff) + RESET)
        max_val = r.get("max")
        if max_val is not None:
            print(ORANGE + t("impact_users_ligne",
                              label="Max", ms=_fmt_ms(max_val), n="≥1") + RESET)

def afficher_session_bilan(histos_session, max_p99_session, nb_scans_session):
    """O — Bilan HDR cumulatif correct en fin de session --interval."""
    if not histos_session:
        return
    total_scans = max(nb_scans_session.values()) if nb_scans_session else 0
    print(t("session_bilan_titre", scans=total_scans))
    for url, hist in histos_session.items():
        nb   = hist.get_total_count()
        s    = hdr_stats(hist)
        print(t("session_bilan_url",   url=url, nb=nb))
        print(t("session_bilan_stats", p50=_fmt_ms(s["p50"]), p99=_fmt_ms(s["p99"]),
                                        p999=_fmt_ms(s["p999"]), max=_fmt_ms(s["max"])))
        if url in max_p99_session:
            print(t("session_bilan_max_p99", v=_fmt_ms(max_p99_session[url])))

def afficher_assertions(assert_checks):
    if not assert_checks:
        return
    print(t("assert_titre"))
    if "_erreur" in assert_checks:
        print(t("assert_erreur", msg=assert_checks["_erreur"]))
        return
    largeur = max(len(c) for c in assert_checks) + 2
    for cle, c in assert_checks.items():
        statut = (VERT + t("slo_check_ok") + RESET) if c["ok"] else (ROUGE + t("slo_check_nok") + RESET)
        print("  " + cle.ljust(largeur) + c["attendu"].ljust(30) + "→  " + c["recu"].ljust(20) + statut)

def afficher_analyse_slo(slo_checks):
    if not slo_checks:
        return
    print(t("slo_titre"))
    largeur_cle = max(len(c) for c in slo_checks) + 2
    for cle, c in slo_checks.items():
        unite  = SLO_UNITES.get(cle, "ms")
        sep    = " " if unite else ""
        v_fmt  = f"{c['valeur']:.1f}" if unite == "ms" else str(c["valeur"])
        s_fmt  = f"{c['seuil']:.1f}"  if unite == "ms" and isinstance(c["seuil"], float) else str(c["seuil"])
        valeur = v_fmt + sep + unite
        seuil  = s_fmt + sep + unite
        op     = c.get("op", "<=")
        statut = (VERT + t("slo_check_ok") + RESET) if c["ok"] else (ROUGE + t("slo_check_nok") + RESET)
        print("  " + cle.ljust(largeur_cle) + valeur.rjust(12) + f"  {op}  " + seuil.ljust(12) + statut)
    print("  " + "─" * 52)
    nb_ok    = sum(1 for c in slo_checks.values() if c["ok"])
    nb_total = len(slo_checks)
    if nb_ok == nb_total:
        print(VERT  + t("slo_bilan_ok",  ok=nb_ok, total=nb_total) + RESET)
    else:
        print(ROUGE + t("slo_bilan_nok", ok=nb_ok, total=nb_total) + RESET)

def afficher_comparaison_baseline(comparaisons, date):
    if not comparaisons:
        return
    print(t("baseline_titre", date=date))
    for c in comparaisons:
        signe     = "+" if c["delta_pct"] >= 0 else ""
        delta_str = (signe + str(c["delta_pct"]) + "%").rjust(6)
        if c["statut"] == "regression":
            statut_str = ORANGE + t("baseline_regression") + RESET
        elif c["statut"] == "amelioration":
            statut_str = VERT + t("baseline_amelioration") + RESET
        else:
            statut_str = VERT + t("baseline_stable") + RESET
        avant_str = (f"{c['avant']:.1f} ms").rjust(9)
        apres_str = (f"{c['apres']:.1f} ms").ljust(9)
        print("    " + c["nom"].ljust(10) + ": " + avant_str + " → " + apres_str + "  " + delta_str + "  " + statut_str)

def afficher_http_timing(ttfb_p50, transfert_p50, total_p50):
    if ttfb_p50 is None or transfert_p50 is None:
        return
    print(t("http_timing"))
    print(t("ttfb",      v=_fmt_ms(ttfb_p50)))
    print(t("transfert", v=_fmt_ms(transfert_p50)))
    print(t("total_p50", v=_fmt_ms(total_p50)))

def afficher_resultat(r, slo_checks=None, comparaison_baseline=None, verbosity="full",
                      nb_ressources=None, req_par_heure=None):
    full = verbosity == "full"

    if r["erreur"]:
        print(r["url"] + " -> " + r["message"])
        return

    print(r["url"])
    if r.get("co_correction"):
        print(VERT + t("co_correction_active",
                        s=r.get("co_intervalle_s", "?"),
                        n=r.get("nb_mesures", "?")) + RESET)
    print(t("http_dist", n=r.get("nb_mesures", "?")))
    print(t("moyenne", v=_fmt_ms(r["moyenne"]), min=_fmt_ms(r["min"]), max=_fmt_ms(r["max"])))
    print(t("p50",  v=_fmt_ms(r["p50"])))
    print(t("p75",  v=_fmt_ms(r["p75"])))
    print(t("p90",  v=_fmt_ms(r["p90"])))
    print(t("p95",  v=_fmt_ms(r["p95"])))
    print(t("p99",  v=_fmt_ms(r["p99"])))
    print(t("p999", v=_fmt_ms(r["p999"])))
    if full:
        afficher_http_timing(r.get("ttfb_p50"), r.get("transfert_p50"), r.get("p50"))
    print(t("stabilite") + indicateur_stabilite(r["p50"], r["p99"]))
    if r.get("ip_mode"):
        print(t("dns_ip_na"))
    else:
        print(t("dns", v=_fmt_ms(r["dns_moyenne"]), min=_fmt_ms(r["dns_min"]), max=_fmt_ms(r["dns_max"])))
        if full:
            afficher_dns_ttl(r.get("dns_ttl"))

    if full:
        if r.get("traceroute_detail") is not None:
            afficher_traceroute_detail(r["traceroute_detail"], r.get("trdetail_nb_sondages", 5))
        elif r.get("traceroute") is not None:
            afficher_traceroute(r["traceroute"])
        if "icmp" in r or "tcp" in r or "tls" in r:
            print("")
            afficher_protocoles(r.get("icmp"), r.get("tcp"), r.get("tls"), r.get("p50"), r["url"])
        if r.get("icmp_ms") is not None:
            afficher_scoring_standards(r["icmp_ms"], r.get("icmp_jitter_ms"), r.get("icmp_loss_pct"))
        if "cdn_info" in r:
            afficher_cdn(r["cdn_info"])
        if r.get("tls_info") is not None:
            afficher_tls_info(r["tls_info"])
        if r.get("path_mtu") is not None:
            afficher_path_mtu(r["path_mtu"])
        afficher_assertions(r.get("assert_checks"))

    afficher_analyse_slo(slo_checks)
    if full:
        afficher_impact_utilisateur(r, nb_ressources, req_par_heure)
    if comparaison_baseline:
        afficher_comparaison_baseline(comparaison_baseline["lignes"], comparaison_baseline["date"])
    print("")

# ── Mesure d'un site (une itération) ─────────────────────────────────────────

def _mediane(valeurs):
    if not valeurs:
        return None
    s = sorted(valeurs)
    return round(s[len(s) // 2], 2)

def _mesurer_site(site_cfg, args, verify_tls):
    """Mesure un site et retourne le dict résultat, ou None si aucune donnée."""
    site    = site_cfg["url"]
    slo     = site_cfg.get("slo")
    asserts = site_cfg.get("assert")

    if not (site.startswith("http://") or site.startswith("https://")):
        print(t("url_invalide", url=site))
        return {"url": site, "erreur": True, "type_erreur": "url", "message": site}

    hostname = site.split("//")[-1].split("/")[0]
    is_https = site.startswith("https://")
    ip_mode  = est_adresse_ip(hostname)

    if ip_mode:
        port = 443 if is_https else 80
        joignable, msg = verifier_ip_joignable(hostname, port)
        if not joignable:
            print(t("ip_non_joignable", msg=msg))
            return {"url": site, "erreur": True, "type_erreur": "ip", "message": msg}

    hist_http        = creer_histogramme()
    mesures_dns      = []
    ttfb_mesures     = []
    transfert_mesures = []
    erreur           = None
    icmp_result      = {}
    tcp_result       = {}
    tls_result       = {}
    tr_result        = {}
    cdn_result       = {}
    tls_info_result  = {}
    dns_ttl_result   = {}
    pmtu_result       = {}
    trdetail_result   = {}

    icmp_thread = threading.Thread(
        target=lambda: icmp_result.update(
            {"icmp": mesurer_icmp(hostname, nb_mesures=args.nombre)}
        )
    )
    tcp_thread = threading.Thread(
        target=lambda: tcp_result.update(
            {"tcp": mesurer_tcp(site, nb_mesures=args.nombre)}
        )
    )
    tls_thread = threading.Thread(
        target=lambda: tls_result.update(
            {"tls": mesurer_tls(site, nb_mesures=args.nombre, timeout=args.timeout, verify=verify_tls)}
        )
    )
    tr_thread = threading.Thread(
        target=lambda: tr_result.update(
            {"tr": mesurer_traceroute(hostname)}
        )
    )
    cdn_thread = threading.Thread(
        target=lambda: cdn_result.update(
            {"cdn": detecter_cdn(site, timeout=args.timeout)}
        )
    )
    tls_info_thread = threading.Thread(
        target=lambda: tls_info_result.update(
            {"tls_info": inspecter_tls(hostname, timeout=args.timeout, verify=verify_tls)}
        )
    )
    dns_ttl_thread = threading.Thread(
        target=lambda: dns_ttl_result.update(
            {"dns_ttl": mesurer_dns_ttl(hostname, timeout=args.timeout)}
        )
    )
    pmtu_thread = threading.Thread(
        target=lambda: pmtu_result.update(
            {"pmtu": decouvrir_path_mtu(hostname, timeout=args.timeout)}
        )
    )
    _nb_sondages = 5
    trdetail_thread = threading.Thread(
        target=lambda: trdetail_result.update(
            {"trdetail": mesurer_traceroute_detail(hostname, nb_sondages=_nb_sondages, timeout=args.timeout)}
        )
    )

    icmp_thread.start()
    tcp_thread.start()
    cdn_thread.start()
    if not ip_mode:
        dns_ttl_thread.start()
    if is_https:
        tls_thread.start()
        if args.tls_info:
            tls_info_thread.start()
    if args.traceroute:
        tr_thread.start()
    if getattr(args, "path_mtu", False):
        pmtu_thread.start()
    if getattr(args, "traceroute_detail", False):
        trdetail_thread.start()

    # Correction coordinated omission (Gil Tene) : activée uniquement en mode
    # --interval, où un taux de mesure fixe est défini.
    intervalle_us = int(args.interval * 1_000_000 / args.nombre) if args.interval else None

    with tqdm(
        total=args.nombre,
        desc=site,
        unit="ping",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
        colour='yellow'
    ) as barre:
        for _ in range(args.nombre):
            r = mesurer_site(site, nb_mesures=1, timeout=args.timeout, verify_tls=verify_tls)
            if r["erreur"]:
                tqdm.write(site + " -> " + r["message"])
                erreur = r
                break
            hdr_enregistrer(hist_http, r["moyenne"], intervalle_us)
            if r["dns_moyenne"] is not None:
                mesures_dns.append(r["dns_moyenne"])
            if r.get("ttfb_ms") is not None:
                ttfb_mesures.append(r["ttfb_ms"])
            if r.get("transfert_ms") is not None:
                transfert_mesures.append(r["transfert_ms"])
            barre.update(1)

    icmp_thread.join()
    tcp_thread.join()
    cdn_thread.join()
    if not ip_mode:
        dns_ttl_thread.join()
    if is_https:
        tls_thread.join()
        if args.tls_info:
            tls_info_thread.join()
    if args.traceroute:
        tr_thread.join()
    if getattr(args, "path_mtu", False):
        pmtu_thread.join()
    if getattr(args, "traceroute_detail", False):
        trdetail_thread.join()

    if erreur:
        return erreur

    if hist_http.get_total_count() == 0:
        return None

    stats      = hdr_stats(hist_http)
    icmp       = icmp_result.get("icmp")
    tcp        = tcp_result.get("tcp")
    tls        = tls_result.get("tls") if is_https else None
    traceroute = tr_result.get("tr") if args.traceroute else None
    cdn_info   = cdn_result.get("cdn")

    p50        = stats["p50"]
    p99        = stats["p99"]
    tcp_moy    = tcp["moyenne"] if tcp else None
    tls_moy    = tls["moyenne"] if tls else None
    surcharge  = round((tcp_moy or 0) + (tls_moy or 0), 1)
    http_keepalive = round(p50 - surcharge, 1) if surcharge > 0 and p50 > surcharge else None

    resultat_final = {
        "url":         site,
        "erreur":      False,
        "type_erreur": None,
        "message":     None,
        "nb_mesures":  hist_http.get_total_count(),
        "ip_mode":     ip_mode,
        **stats,
        "dns_moyenne":     round(sum(mesures_dns) / len(mesures_dns), 2) if mesures_dns else None,
        "dns_min":         min(mesures_dns) if mesures_dns else None,
        "dns_max":         max(mesures_dns) if mesures_dns else None,
        "ttfb_p50":        _mediane(ttfb_mesures),
        "transfert_p50":   _mediane(transfert_mesures),
        "icmp":            icmp,
        "tcp":             tcp,
        "tls":             tls,
        "traceroute":      traceroute,
        "cdn_info":        cdn_info,
        "stability_ratio": round(p99 / p50, 2) if p50 > 0 else None,
        "icmp_ms":         icmp["moyenne"] if icmp else None,
        "icmp_jitter_ms":  icmp["jitter"]   if icmp else None,
        "icmp_loss_pct":   icmp["loss_pct"] if icmp else None,
        "tcp_ms":          tcp_moy,
        "tcp_jitter_ms":   tcp["jitter"] if tcp else None,
        "tls_ms":          tls_moy,
        "http_keepalive_ms":   http_keepalive,
        "nb_hops":         traceroute["nb_hops"] if traceroute else None,
        "tls_info":        tls_info_result.get("tls_info") if args.tls_info and is_https else None,
        "mos":             calculer_mos(
                               icmp["moyenne"] if icmp else 0.0,
                               icmp["jitter"]  if icmp else 0.0,
                               icmp["loss_pct"] if icmp else 0.0,
                           )["mos"] if icmp else None,
        "co_correction":   intervalle_us is not None,
        "co_intervalle_s": args.interval if intervalle_us else None,
        "dns_ttl":         dns_ttl_result.get("dns_ttl") if not ip_mode else None,
        "path_mtu":        pmtu_result.get("pmtu") if getattr(args, "path_mtu", False) else None,
        "traceroute_detail": trdetail_result.get("trdetail") if getattr(args, "traceroute_detail", False) else None,
        "trdetail_nb_sondages": _nb_sondages,
    }
    slo_checks    = verifier_slo(resultat_final, slo) if slo else None
    assert_checks = verifier_assertions(site, asserts, timeout=args.timeout) if asserts else None
    resultat_final["slo_checks"]    = slo_checks
    resultat_final["assert_checks"] = assert_checks

    return resultat_final

# ── Détection de dégradation ──────────────────────────────────────────────────

def detecter_degradation(current, previous):
    """Retourne la liste des métriques qui ont augmenté de plus de SEUIL_DEGRADATION."""
    alertes = []
    metriques = [
        ("p50",         current.get("p50"),         previous.get("p50")),
        ("p95",         current.get("p95"),         previous.get("p95")),
        ("p99",         current.get("p99"),         previous.get("p99")),
        ("dns_moyenne", current.get("dns_moyenne"),  previous.get("dns_moyenne")),
        ("icmp_ms",     current.get("icmp_ms"),     previous.get("icmp_ms")),
    ]
    for metric, val_curr, val_prev in metriques:
        if val_curr is None or val_prev is None or val_prev <= 0:
            continue
        delta = (val_curr - val_prev) / val_prev
        if delta >= SEUIL_DEGRADATION:
            alertes.append((metric, round(val_prev, 1), round(val_curr, 1), round(delta * 100)))
    return alertes

# ── Webhook ──────────────────────────────────────────────────────────────────

def _declencher_webhook(webhook_cfg, event, url, data):
    """Envoie le webhook en arrière-plan (thread daemon, non-bloquant)."""
    hook_url = (webhook_cfg or {}).get("url", "")
    if not hook_url:
        return
    payload = {"source": "ltiprobe", "event": event, "url": url,
                "heure": _heure_locale(), **data}
    threading.Thread(target=envoyer_webhook, args=(hook_url, payload), daemon=True).start()
    print(t("webhook_envoye", event=event))

# ── Point d'entrée ────────────────────────────────────────────────────────────

def main():
    global t
    try:
        args, cfg = parse_arguments()
    except FileNotFoundError as e:
        print("Erreur : " + str(e), file=sys.stderr)
        sys.exit(1)

    t = get_translator(cfg.get("language", "FR").upper())
    verify_tls = not args.no_verify_tls

    if args.merge:
        resultats = merger_histogrammes(args.merge)
        afficher_merge(resultats)
        return

    baseline = {}
    if args.baseline:
        try:
            baseline = charger_baseline(args.baseline)
        except (FileNotFoundError, ValueError) as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)

    # Sites loading priority:
    # 1. CLI positional args  (ltiprobe https://example.com)
    # 2. --sites-file FILE    (explicit override)
    # 3. sites.yaml           (auto-detected if present)
    # 4. ltiprobe.yaml sites: (backward compatibility)
    if args.sites:
        sites_config = [{"url": s} for s in args.sites]
    else:
        try:
            sites_config = config.charger_sites(args.sites_file)
        except (FileNotFoundError, ValueError) as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
        if not sites_config:
            # fallback: sites: key in ltiprobe.yaml
            sites_config = [
                s if isinstance(s, dict) else {"url": s}
                for s in cfg.get("sites", [])
            ]

    cfg_file = args.config_file or config.FICHIER_DEFAUT
    print(t("header", ver=__version__, n=args.nombre, cfg=cfg_file) + "\n")

    reseau_info = detecter_reseau()
    afficher_reseau(reseau_info)
    print(t("mesures_titre"))

    webhook_cfg       = cfg.get("webhook")
    nb_ressources     = cfg.get("resources_per_page") or None
    req_par_heure     = cfg.get("requests_per_hour") or None

    tous_resultats    = []
    prev_results      = {}  # {url: resultat} — dernier résultat réussi par site
    degradation_since = {}  # {url: {metric: heure_str}} — heure de première détection
    histos_session    = {}  # O — {url: HdrHistogram} cumulatif
    max_p99_session   = {}  # O — {url: float} max P99 observé
    nb_scans_session  = {}  # O — {url: int}

    iteration = 0
    try:
        while True:
            iteration += 1
            if args.interval:
                print(t("intervalle_titre", n=iteration, heure=_heure_scan()))

            for site_cfg in sites_config:
                r = _mesurer_site(site_cfg, args, verify_tls)
                if r is None:
                    continue

                tous_resultats.append(r)
                cmp_baseline = None
                if baseline and not r.get("erreur") and r["url"] in baseline:
                    entry = baseline[r["url"]]
                    lignes = comparer_baseline(r, entry)
                    if lignes:
                        cmp_baseline = {"lignes": lignes, "date": entry["date"]}
                r["baseline_comparaison"] = cmp_baseline
                afficher_resultat(r, r.get("slo_checks"), cmp_baseline, args.verbosity,
                                  nb_ressources=nb_ressources, req_par_heure=req_par_heure)

                # O — alimenter l'histogramme cumulatif de session
                if args.interval and not r.get("erreur"):
                    enc = r.get("hdr_encode")
                    if enc is not None:
                        hist_src = _HdrHistogram.decode(enc)
                        if r["url"] not in histos_session:
                            histos_session[r["url"]] = creer_histogramme()
                        histos_session[r["url"]].add(hist_src)
                        p99 = r.get("p99") or 0.0
                        if p99 > max_p99_session.get(r["url"], 0.0):
                            max_p99_session[r["url"]] = p99
                        nb_scans_session[r["url"]] = nb_scans_session.get(r["url"], 0) + 1

                # Webhook SLO
                if webhook_cfg and not r.get("erreur"):
                    on = webhook_cfg.get("on", "slo_violation")
                    if on in ("slo_violation", "all"):
                        slo_checks = r.get("slo_checks") or {}
                        violations = {k: v for k, v in slo_checks.items() if not v["ok"]}
                        if violations:
                            _declencher_webhook(webhook_cfg, "slo_violation", r["url"], {
                                "violations": [
                                    {"slo": k, "valeur": v["valeur"], "seuil": v["seuil"]}
                                    for k, v in violations.items()
                                ]
                            })

                url = r["url"]
                if args.interval and not r.get("erreur") and url in prev_results:
                    heure_now = _heure_locale()
                    alertes   = detecter_degradation(r, prev_results[url])
                    if alertes:
                        degraded = set()
                        for metric, avant, apres, pct in alertes:
                            nom       = _NOMS_METRIQUES.get(metric, metric)
                            heure_deg = degradation_since.setdefault(url, {}).setdefault(metric, heure_now)
                            print(ORANGE + t("degradation_alerte", metric=nom, avant=avant, apres=apres, pct=pct, heure=heure_deg) + RESET)
                            degraded.add(metric)
                        if webhook_cfg and webhook_cfg.get("on", "slo_violation") in ("degradation", "all"):
                            _declencher_webhook(webhook_cfg, "degradation", url, {
                                "alertes": [
                                    {"metric": m, "avant": a, "apres": ap, "delta_pct": p}
                                    for m, a, ap, p in alertes
                                ]
                            })
                        for metric in list(degradation_since.get(url, {}).keys()):
                            if metric not in degraded:
                                del degradation_since[url][metric]
                    else:
                        degradation_since.pop(url, None)

                if not r.get("erreur"):
                    prev_results[url] = r

            if not args.interval:
                break

            print(t("intervalle_attente", s=args.interval))
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print()

    # O — bilan cumulatif si session --interval avec ≥2 scans
    if args.interval and histos_session and max(nb_scans_session.values(), default=0) >= 2:
        afficher_session_bilan(histos_session, max_p99_session, nb_scans_session)

    if args.csv and tous_resultats:
        fichier = sauvegarder_csv(tous_resultats)
        print(t("csv_sauvegarde", f=fichier))
        if args.baseline:
            fichier_cmp = sauvegarder_csv_comparaison(tous_resultats)
            print(t("csv_comparaison", f=fichier_cmp))

    if args.prometheus_out and tous_resultats:
        sauvegarder_prometheus(tous_resultats, args.prometheus_out)
        print(t("prometheus_sauvegarde", f=args.prometheus_out))

if __name__ == "__main__":
    main()
