# -*- coding: utf-8 -*-
import os
import yaml

FICHIER_DEFAUT = "ping-tool.yaml"

_DEFAULTS = {
    "nb_mesures": 10,
    "timeout":    10,
    "langue":     "FR",
    "sites": [
        {"url": "https://google.com"},
        {"url": "https://github.com"},
        {"url": "https://youtube.com"},
        {"url": "https://apple.com"},
    ],
}

def charger(filepath=None):
    """Charge la configuration depuis un fichier YAML.

    Utilise FICHIER_DEFAUT si filepath est None ou absent.
    Retourne un dict fusionné avec les valeurs par défaut.
    """
    path = filepath or FICHIER_DEFAUT
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return {**_DEFAULTS, **data}
    if filepath:
        raise FileNotFoundError(f"Fichier de configuration introuvable : {filepath}")
    return _DEFAULTS.copy()

# Chargement initial depuis le fichier par défaut (pour compatibilité imports directs)
_cfg = charger()

NB_MESURES   = _cfg["nb_mesures"]
TIMEOUT      = _cfg["timeout"]
LANGUE       = _cfg.get("langue", "FR").upper()
SITES_DEFAUT = _cfg["sites"]
FICHIER_CSV  = None
