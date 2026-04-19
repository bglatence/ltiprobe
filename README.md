# ping-tool

Mesure les temps de reponse HTTP et DNS de sites web depuis le Terminal.

## Installation

pip install ping-tool-bglatence

## Utilisation

    # Sites par defaut
    ping-tool

    # Sites personnalises
    ping-tool https://apple.com https://amazon.com

    # 10 mesures par site
    ping-tool -n 10

    # Sauvegarder en CSV
    ping-tool --csv

    # Aide
    ping-tool --help

## Exemple de sortie

    https://google.com
      HTTP  -> moyenne: 124.35 ms  min: 118.2  max: 131.5
      DNS   -> moyenne: 8.42 ms  min: 7.1  max: 9.8
      DNS % -> 6.8% du temps total

## Licence

MIT

[![PyPI version](https://badge.fury.io/py/ping-tool-bglatence.svg)](https://pypi.org/project/ping-tool-bglatence/)