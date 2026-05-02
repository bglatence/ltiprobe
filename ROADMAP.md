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

| # | Évolution | Statut |
|---|---|---|
| A | Jitter + packet loss | ✅ v1.0.0 |
| B | MOS score (ITU-T G.107) | ✅ v1.0.0 |
| C | Correction coordinated omission | ✅ v1.0.0 |
| D | Comportement du cache DNS (TTL) | ✅ v1.0.0 |
| E | Path MTU discovery (`--path-mtu`) | ✅ v1.4.0 |
| F | Analyse hop-by-hop jitter/loss (`--traceroute-detail`) | ✅ v1.5.0 |
| G | TLS session resumption timing | 🔲 à évaluer |
| H | Merge d'histogrammes distribués (`--merge`) | ✅ v1.5.5 |

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
| **Jitter (StDev RTT)** | ✅ v1.0 | — | ✅ | — | ✅ |
| **Packet loss %** | ✅ v1.0 | — | ✅ | ✅ | ✅ |
| **MOS score** | ✅ v1.0 | — | — | — | ✅ |
| **Correction coordinated omission** | ✅ v1.0 | — | — | — | ✅ |
| **DNS TTL / cache behavior** | ✅ v1.0 | — | — | — | ✅ |
| **Path MTU discovery** | ✅ v1.4 | — | — | — | ✅ |
| **Hop-by-hop jitter/loss par saut** | ✅ v1.5 | — | ✅ | — | ✅ |
| **TLS session resumption timing** | 🔲 | — | — | — | ✅ |
| **Merge histogrammes distribués** | ✅ v1.5.5 | — | — | — | — |
| Multi-langue (FR/EN/ES/DE/JA/ZH/PT) | ✅ v1.5 | — | — | — | — |

---

## Évolutions futures envisagées

Items identifiés pour les prochaines itérations. Aucune priorité définie à ce stade.

---

### I. Mécanisme de collecte automatique (exécution distribuée)

Permettre à plusieurs instances de ltiprobe (sondes géographiquement distribuées) d'envoyer
automatiquement leurs résultats CSV vers un point de collecte central, pour alimenter le
`--merge` sans étape manuelle.

Pistes envisagées : push vers S3/objet, endpoint HTTP POST, ou bus de messages léger.
Complémentaire de l'évolution H déjà livrée (merge local).

---

### J. Interface utilisateur web

Créer une interface de visualisation des résultats ltiprobe : tableau de bord des mesures,
graphiques de distribution HDR, suivi des SLO dans le temps, comparaison multi-sites.

Pourrait s'appuyer sur les CSV et exports Prometheus existants comme source de données.

---

### K. Application mobile Android

Portage ou client mobile Android permettant de lancer des mesures ltiprobe depuis un appareil
mobile et de visualiser les résultats — utile pour les audits terrain et la comparaison
Wi-Fi / cellulaire / filaire.

---

### L. Évaluation et mesure de l'option BBR (TCP)

Mesurer l'impact de l'algorithme de contrôle de congestion BBR (Bottleneck Bandwidth and
Round-trip propagation time, Google) sur la latence et le débit perçu, et détecter si le
serveur distant l'utilise.

Cas d'usage : comparaison CUBIC vs BBR sur des liens à forte latence ou à perte de paquets.

---

### M. Support IPv6

Ajouter la prise en charge native d'IPv6 : résolution AAAA, mesures ICMP6, comparaison
IPv4 vs IPv6 sur les mêmes cibles.

Lié à l'item 11 du tableau initial (🔲 à évaluer). Utile pour les environnements dual-stack
et la migration progressive vers IPv6.

---

## Inspirations — blog "Latency Tip of the Day" (Gil Tene, 2014)

Gil Tene est l'auteur de la bibliothèque HdrHistogram utilisée par ltiprobe. Son blog expose
les erreurs les plus courantes dans la mesure de latence et les principes pour les éviter.
Les items ci-dessous en sont directement inspirés.

---

### N. Affichage explicite du Max dans le résumé SLO
**Inspiré de** *"If you are not measuring and/or plotting Max, what are you hiding (from)?"*

ltiprobe rapporte déjà P99.9, mais ne met pas en avant la valeur maximale observée dans le
résumé SLO. Or le Max est le seul indicateur qui ne peut pas masquer un incident : un GC pause,
un cold start, un timeout réseau s'y voient immédiatement. Gil Tene argumente que ne pas
afficher le Max revient à se cacher la vérité.

Ajout envisagé : une ligne `Max : X ms` dans la section SLO, avec alerte si `max_seuil` est
dépassé dans le fichier de configuration.

---

### O. Agrégation correcte des percentiles en mode `--interval`
**Inspiré de** *"You can't average percentiles. Period."*

En mode monitoring continu, il est tentant de moyenner les P99 de chaque fenêtre temporelle —
ce qui est mathématiquement invalide. La valeur correcte à rapporter est le **max des P99**
sur la session, ou mieux, maintenir un histogramme HDR cumulatif qui absorbe toutes les
fenêtres sans perte de précision (ce que `hdrh` supporte nativement via `add()`).

Ajout envisagé : en fin de session `--interval`, afficher le bilan cumulatif (`max P99 observé`,
`P99.9 global`, `Max absolu`) plutôt qu'une simple moyenne des résultats par fenêtre.

---

### P. Détection de bimodalité de la distribution
**Inspiré de** *"Average: a random number that falls somewhere between the maximum and 1/2 the median"*

Quand une distribution est bimodale — 95 % des requêtes à 20 ms, 5 % à 800 ms — la moyenne
tombe entre les deux pics et ne représente aucune réalité mesurable. Gil Tene démontre que
dans ce cas la moyenne peut être inférieure à la médiane/2, rendant tout raisonnement basé
sur elle trompeur.

Ajout envisagé : analyser le histogramme HDR pour détecter un gap significatif entre deux
populations de valeurs et afficher `⚠ distribution bimodale — moyenne non représentative`.

---

### Q. Estimateur d'impact utilisateur par volume de ressources
**Inspiré de** *"MOST page loads will experience the 99th percentile server response"*

Une page web typique charge 30 à 100 ressources. Avec 42 requêtes parallèles, la probabilité
qu'un utilisateur subisse au moins une réponse au-delà du P99 est quasi certaine. La formule
est simple : `P(au moins 1 > seuil) = 1 - (1 - p_dépassement)^N`.

Ajout envisagé : paramètre `resources_per_page` dans `ltiprobe.yaml`, avec affichage
`P(≥1 requête > 200ms sur 40 ressources) = 86%` — traduction directe de la latence réseau
en ressenti utilisateur concret.

---

### R. Traduction des percentiles en utilisateurs affectés
**Inspiré de** *"Median Server Response Time: The number that 99.9999999% of page views can be worse than"*

Afficher uniquement des ratios (P99 = 1 %) donne une fausse impression de rareté. Avec
10 000 requêtes par heure, ce 1 % représente 100 utilisateurs toutes les 60 minutes qui vivent
une expérience dégradée. Gil Tene souligne que le médian est "le nombre dont 99,999…% des
pages vues peuvent être pires".

Ajout envisagé : paramètre `requests_per_hour` dans `ltiprobe.yaml`, avec affichage
`P99 → ~100 utilisateurs/heure affectés` en regard de chaque percentile SLO.

---

### S. Analyse du compound latency (impact page complète)
**Inspiré de** *"MOST page loads will experience the 99th percentile server response"*

Complémentaire de Q mais plus avancé : simuler N requêtes séquentielles ou parallèles et
mesurer la latence **totale** de la page (somme séquentielle ou max parallèle), puis en
rapporter la distribution HDR complète. Cela permet de répondre à "quelle est la latence
réelle perçue pour le chargement complet d'une page ?" plutôt que "quelle est la latence
d'une requête individuelle ?".

Ajout envisagé : flag `--compound N` pour exécuter N requêtes et mesurer le temps total.

---

### T. Rapport d'audit de la configuration de monitoring (`--audit`)
**Inspiré de** *"Q: What's wrong with this picture? A: Everything!"* et *"Measure what you need to monitor"*

Générer un rapport qui critique la configuration ltiprobe elle-même selon les principes de
Gil Tene : SLO ciblant le P50 (insuffisant), absence de seuil sur le Max, fenêtre de mesure
trop courte pour capturer les événements rares, utilisation implicite de la moyenne.

Ajout envisagé : `ltiprobe --audit` produit un checklist commenté avec des recommandations
concrètes de configuration, sans effectuer de mesures réseau.

---

### U. Avertissement sur les opérations invalides sur les percentiles
**Inspiré de** *"You can't average percentiles. Period."*

Si l'utilisateur compare deux fichiers `--baseline` issus de fenêtres temporelles différentes
et que ltiprobe calcule implicitement une moyenne de P99, il devrait avertir que l'opération
est mathématiquement incorrecte. De même pour toute tentative d'agréger des percentiles par
addition ou division.

Ajout envisagé : détection automatique des contextes où une moyenne de percentiles serait
calculée, avec message `⚠ averaging percentiles is invalid — use max(P99) or merge raw histograms`.
