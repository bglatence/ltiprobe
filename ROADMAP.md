# Roadmap ltiprobe

Évolutions potentielles identifiées par analyse comparative avec des outils similaires.

---

## Statut des évolutions initiales

| # | Évolution | Statut |
|---|---|---|
| 1 | Décomposition TTFB / transfert | ✅ v0.6.0 |
| 2 | Monitoring continu (`--interval`) | ✅ v0.5.0 |
| 3 | Validation de la réponse HTTP | ✅ v0.4.0 |
| 4 | Comparaison avec une baseline CSV | ✅ v0.7.0 |
| 5 | Export Prometheus (`--prometheus-out`) | ✅ v0.8.0 |
| 6 | Analyse de la chaîne de redirections | ❌ abandonné — HTTP→HTTPS quasi universel (95–99 % du trafic déjà HTTPS) |
| 7 | Informations TLS avancées (`--tls-info`) | ✅ v0.8.0 |
| 8 | Détection CDN et cache | ✅ v0.3.0 |
| 9 | Graphique TUI / sparkline | 🔲 à évaluer |
| 10 | Requêtes concurrentes (`--concurrent`) | 🔲 à évaluer |
| 11 | Comparaison IPv4 vs IPv6 | 🔲 à évaluer |
| 12 | Profils multi-environnements (`--config-file`) | ✅ v0.3.0 |
| 13 | Webhook d'alerte SLO | ✅ v0.8.0 |
| 14 | Détection redirections dans les assertions | 🔲 à évaluer |

---

## Nouvelles propositions — étude de marché 2026-04-29

Analyse comparative approfondie incluant : hey, vegeta, wrk2, mtr, smokeping, blackbox_exporter,
gatling, locust, et les solutions enterprise **Spirent**, **Accedian (Cisco)**, **Viavi**,
**Keysight (Ixia)**, **ThousandEyes**, **Catchpoint**, **Dynatrace Synthetic**.

---

### A. Jitter + packet loss
**Complexité : faible**
**Inspiré de** mtr, smokeping, Catchpoint

Ajouter deux métriques dérivées des mesures ICMP existantes, sans requête réseau supplémentaire :
- **Jitter** : écart-type des RTT sur la fenêtre de mesures
- **Packet loss %** : ratio paquets envoyés / reçus

```
  ICMP  (network)  :  12.3 ms  min: 11.1  max: 13.5  jitter: 1.2 ms  loss: 0%
```

Ces deux métriques sont la base du MOS score (voir évolution B) et ferment le gap vs smokeping/mtr.

---

### B. MOS score (Mean Opinion Score)
**Complexité : faible**
**Fonctionnalité enterprise democratisée — Keysight la facture sous licence**

Le MOS score (échelle 1.0–4.5) évalue la qualité perçue d'un flux voix/vidéo à partir de
latence, jitter et packet loss via la formule ITU-T E-Model. Aucun outil OSS ne le propose.

```
  MOS   : 4.2 / 4.5  ✓  (latence: 12ms  jitter: 1.2ms  loss: 0%)
```

Implémentation : ~30 lignes Python, zéro dépendance.
Utile pour les équipes VoIP, UC, WebRTC, vidéoconférence.

---

### C. Correction de la coordinated omission
**Complexité : faible**
**Inspiré de** wrk2 (Gil Tene — référence académique)

La *coordinated omission* est le principal biais de précision des outils de mesure de latence :
quand le serveur est lent, les mesures suivantes attendent — sous-estimant la latence réelle.
`hdrh` expose déjà `record_corrected_value(valeur, intervalle_attendu)` — c'est une correction
en une ligne, activée en mode `--interval`.

Ajouterait une crédibilité technique forte face à hey, wrk et locust qui ne corrigent pas ce biais.

---

### D. Comportement du cache DNS (TTL)
**Complexité : faible**
**Gap OSS réel — aucun outil ne le fait**

Mesurer si la résolution DNS vient du cache local (TTL non expiré → très rapide) ou d'une
résolution complète (TTL expiré → aller-retour vers le résolveur). Détectable par comparaison
de timing entre requêtes DNS successives.

```
  DNS   ->  8.2 ms (résolution complète)  /  0.3 ms (cache local, TTL: 287s)
```

Utile pour optimiser les TTL DNS et comprendre l'impact des renouvellements.

---

### E. Path MTU discovery
**Complexité : moyenne**
**Fonctionnalité Catchpoint / Spirent — aucun outil OSS l'intègre avec des percentiles**

Trouver la MTU maximale du chemin réseau par dichotomie de sondes ICMP avec le bit DF (Don't
Fragment) positionné. Utile pour diagnostiquer des problèmes de fragmentation sur VPN, tunnels
MPLS ou liens intercontinentaux.

```bash
ltiprobe --mtu-discovery https://api.example.com
```

```
  Path MTU  :  1400 bytes  (tunnel VPN détecté — MTU système : 1500)
```

---

### F. Analyse hop-by-hop avec jitter et loss par saut
**Complexité : moyenne**
**Inspiré de** mtr, ThousandEyes (enterprise)

Étendre le `--traceroute` existant pour afficher, à chaque hop :
- Latence moyenne + jitter
- Packet loss %
- Numéro d'AS (via lookup IP→ASN public)

```
  Hop  1   192.168.1.1       1.2 ms   jitter: 0.1 ms   loss: 0%    AS —
  Hop  5   12.34.56.78      18.4 ms   jitter: 2.1 ms   loss: 2%    AS15169 (Google)
  Hop 10   destination       38.0 ms  jitter: 1.8 ms   loss: 0%    AS15169
```

Replique une fonctionnalité ThousandEyes exclusive (path trace avec AS lookup).

---

### G. TLS session resumption timing
**Complexité : moyenne**
**Gap OSS réel — Dynatrace Synthetic seulement**

Mesurer le delta de latence entre un handshake TLS initial (cold) et une session reprise
(session ticket reuse). Permet de quantifier le gain du TLS resumption et de valider
que le serveur l'implémente correctement.

```
  TLS  handshake initial  :  31 ms
  TLS  session resumption :  12 ms  (-19 ms, -61%)  ✓ session tickets actifs
```

---

### H. Merge d'histogrammes distribués
**Complexité : moyenne**
**Gap OSS réel — aucun outil réseau ne le fait, hdrh le supporte nativement**

Permettre de fusionner des fichiers de résultats provenant de plusieurs sondes géographiques
(ex. : serveur Paris + serveur Montréal + serveur Tokyo) en un seul histogramme agrégé.

```bash
ltiprobe --merge paris.csv montreal.csv tokyo.csv --output global.csv
```

La bibliothèque `hdrh` supporte nativement la sérialisation binaire et `histogram.add()` —
aucune approximation, la fusion est exacte sur les percentiles.

---

## Tableau comparatif mis à jour

| Fonctionnalité | ltiprobe | hey | mtr | blackbox_exporter | Keysight/Spirent |
|---|:---:|:---:|:---:|:---:|:---:|
| Distribution HdrHistogram P50→P99.9 | ✅ | ✅ | — | — | ✅ |
| SLOs par site avec seuils configurables | ✅ | — | — | ✅ | ✅ |
| Indicateur de stabilité p99/p50 | ✅ | — | — | — | — |
| Décomposition ICMP / TCP / TLS / HTTP | ✅ | — | partiel | partiel | ✅ |
| TTFB / décomposition transfert | ✅ | — | — | — | ✅ |
| Détection CDN et statut cache | ✅ | — | — | — | — |
| Inspection certificat TLS | ✅ | — | — | — | ✅ |
| Monitoring continu avec alertes dégradation | ✅ | — | ✅ | — | ✅ |
| Comparaison baseline CSV | ✅ | — | — | — | — |
| Export Prometheus | ✅ | — | — | ✅ | ✅ |
| Webhook d'alerte SLO | ✅ | — | — | — | ✅ |
| Validation HTTP (status, body, header) | ✅ | — | — | ✅ | ✅ |
| Configuration YAML multi-sites | ✅ | — | — | ✅ | ✅ |
| **Jitter (StDev RTT)** | 🔲 | — | ✅ | — | ✅ |
| **Packet loss %** | 🔲 | — | ✅ | ✅ | ✅ |
| **MOS score** | 🔲 | — | — | — | ✅ |
| **Correction coordinated omission** | 🔲 | — | — | — | ✅ |
| **DNS TTL / cache behavior** | 🔲 | — | — | — | ✅ |
| **Path MTU discovery** | 🔲 | — | — | — | ✅ |
| **Hop-by-hop jitter/loss + AS lookup** | 🔲 | — | ✅ | — | ✅ |
| **TLS session resumption timing** | 🔲 | — | — | — | ✅ |
| **Merge histogrammes distribués** | 🔲 | — | — | — | — |
| Multi-langue (FR/EN) | ✅ | — | — | — | — |
