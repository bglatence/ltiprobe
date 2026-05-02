# -*- coding: utf-8 -*-
import os
import yaml

FICHIER_DEFAUT      = "ltiprobe.yaml"
FICHIER_SITES_DEFAUT = "sites.yaml"

_DEFAULTS = {
    "nb_measures":        10,
    "timeout":            10,
    "language":           "FR",
    "verbosity":          "full",
    "resources_per_page": None,  # Q : compound latency estimator
    "requests_per_hour":  None,  # R : percentiles → users/h
    # "sites" key kept for backward compatibility (ltiprobe.yaml with sites: block)
    "sites": [
        {"url": "https://google.com"},
        {"url": "https://github.com"},
        {"url": "https://youtube.com"},
        {"url": "https://apple.com"},
    ],
}

def charger(filepath=None):
    """Load tool configuration from a YAML file.

    Falls back to FICHIER_DEFAUT if filepath is None or missing.
    Transparently migrates legacy keys (nb_mesures → nb_measures, langue → language).
    Returns a dict merged with defaults.
    """
    path = filepath or FICHIER_DEFAUT
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # backward compat: silently migrate old French key names
        if "nb_mesures" in data and "nb_measures" not in data:
            data["nb_measures"] = data.pop("nb_mesures")
        if "langue" in data and "language" not in data:
            data["language"] = data.pop("langue")
        return {**_DEFAULTS, **data}
    if filepath:
        raise FileNotFoundError(f"Configuration file not found: {filepath}")
    return _DEFAULTS.copy()


def charger_sites(filepath=None):
    """Load the list of sites from a YAML file.

    Expected format: a direct YAML list (no root 'sites:' key).
    Each item is either a URL string or a dict {url, slo, assert}.

    Priority:
      1. filepath (explicit --sites-file argument)
      2. FICHIER_SITES_DEFAUT (sites.yaml, auto-detected)

    Returns [] if the file is absent (no explicit filepath given).
    Raises FileNotFoundError if an explicit filepath does not exist.
    """
    path = filepath or FICHIER_SITES_DEFAUT
    if not os.path.exists(path):
        if filepath:
            raise FileNotFoundError(f"Sites file not found: {filepath}")
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    if not isinstance(data, list):
        raise ValueError(f"Sites file must be a YAML list, got {type(data).__name__}: {path}")
    return [s if isinstance(s, dict) else {"url": s} for s in data]


# Module-level constants — loaded once at import time
_cfg = charger()

NB_MEASURES  = _cfg["nb_measures"]
NB_MESURES   = NB_MEASURES   # backward compat alias
TIMEOUT      = _cfg["timeout"]
LANGUAGE     = _cfg.get("language", "FR").upper()
LANGUE       = LANGUAGE      # backward compat alias
SITES_DEFAUT = _cfg["sites"]
FICHIER_CSV  = None
