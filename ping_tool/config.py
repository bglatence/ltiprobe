# -*- coding: utf-8 -*-
import os
import yaml

_CONFIG_FILE = "ping-tool.yaml"

_DEFAULTS = {
    "nb_mesures": 10,
    "timeout": 10,
    "langue": "FR",
    "sites": [
        {"url": "https://google.com"},
        {"url": "https://github.com"},
        {"url": "https://youtube.com"},
        {"url": "https://apple.com"},
    ],
}

def _charger():
    if os.path.exists(_CONFIG_FILE):
        with open(_CONFIG_FILE, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return {**_DEFAULTS, **data}
    return _DEFAULTS.copy()

_cfg = _charger()

NB_MESURES   = _cfg["nb_mesures"]
TIMEOUT      = _cfg["timeout"]
LANGUE       = _cfg.get("langue", "FR").upper()
SITES_DEFAUT = _cfg["sites"]
FICHIER_CSV  = None
