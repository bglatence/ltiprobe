# -*- coding: utf-8 -*-
_TRANSLATIONS: dict[str, dict[str, str]] = {
    "FR": {
        "header":           "Mesure des temps de réponse ({n} essais)...",
        "http_dist":        "  HTTP  distribution ({n} mesures)",
        "moyenne":          "    moyenne : {v} ms   min: {min}   max: {max}",
        "p50":              "    p50     : {v} ms",
        "p75":              "    p75     : {v} ms",
        "p90":              "    p90     : {v} ms",
        "p95":              "    p95     : {v} ms",
        "p99":              "    p99     : {v} ms",
        "p999":             "    p99.9   : {v} ms",
        "stabilite":        "  Stabilité : ",
        "tres_stable":      "très stable  ",
        "stable":           "stable       ",
        "variable":         "variable     ",
        "instable":         "instable     ",
        "ratio":            "(p99/p50 = {r}x)",
        "dns":              "  DNS   -> moyenne: {v} ms  min: {min}  max: {max}",
        "slo_ok":           "  SLO   -> tous les objectifs sont respectés",
        "slo_violation":    "  SLO   -> {n} violation(s)",
        "slo_tag_ok":       "  [SLO <={s}ms  {ok}OK{reset}]",
        "slo_tag_nok":      "  [SLO <={s}ms  {rouge}VIOLATION{reset}]",
        "proto_titre":      "  --- Comparaison protocoles ---",
        "proto_icmp":       "  ICMP  (réseau)     : {v} ms  min: {min}  max: {max}  ({n} paquets)",
        "proto_icmp_na":    "  ICMP  (réseau)     : non disponible",
        "proto_tcp":        "  TCP   (port {p})   : {v} ms  min: {min}  max: {max}",
        "proto_tcp_na":     "  TCP   (port {p})   : non disponible",
        "proto_http":       "  HTTP  (p50)        : {v} ms",
        "csv_sauvegarde":   "Résultats sauvegardés dans : {f}",
    },
    "EN": {
        "header":           "Measuring response times ({n} attempts)...",
        "http_dist":        "  HTTP  distribution ({n} measurements)",
        "moyenne":          "    average : {v} ms   min: {min}   max: {max}",
        "p50":              "    p50     : {v} ms",
        "p75":              "    p75     : {v} ms",
        "p90":              "    p90     : {v} ms",
        "p95":              "    p95     : {v} ms",
        "p99":              "    p99     : {v} ms",
        "p999":             "    p99.9   : {v} ms",
        "stabilite":        "  Stability : ",
        "tres_stable":      "very stable  ",
        "stable":           "stable       ",
        "variable":         "variable     ",
        "instable":         "unstable     ",
        "ratio":            "(p99/p50 = {r}x)",
        "dns":              "  DNS   -> average: {v} ms  min: {min}  max: {max}",
        "slo_ok":           "  SLO   -> all objectives met",
        "slo_violation":    "  SLO   -> {n} violation(s)",
        "slo_tag_ok":       "  [SLO <={s}ms  {ok}OK{reset}]",
        "slo_tag_nok":      "  [SLO <={s}ms  {rouge}VIOLATION{reset}]",
        "proto_titre":      "  --- Protocol comparison ---",
        "proto_icmp":       "  ICMP  (network)    : {v} ms  min: {min}  max: {max}  ({n} packets)",
        "proto_icmp_na":    "  ICMP  (network)    : not available",
        "proto_tcp":        "  TCP   (port {p})   : {v} ms  min: {min}  max: {max}",
        "proto_tcp_na":     "  TCP   (port {p})   : not available",
        "proto_http":       "  HTTP  (p50)        : {v} ms",
        "csv_sauvegarde":   "Results saved to: {f}",
    },
}

def get_translator(lang: str):
    """Retourne une fonction t(key, **kwargs) pour la langue donnée.

    Repli sur FR si la langue est inconnue.
    """
    strings = _TRANSLATIONS.get(lang.upper(), _TRANSLATIONS["FR"])

    def t(key: str, **kwargs: object) -> str:
        return strings[key].format(**kwargs) if kwargs else strings[key]

    return t
