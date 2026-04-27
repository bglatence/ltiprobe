# Roadmap ping-tool

Évolutions potentielles identifiées par analyse comparative avec des outils similaires
(hey, vegeta, mtr, blackbox_exporter, curl, gping, k6).

---

## Priorité haute — valeur immédiate

### 1. Décomposition TTFB vs transfert
**Inspiré de** `curl --write-out`

Séparer le *Time to First Byte* (traitement serveur) du temps de transfert du contenu.
Actuellement, le HTTP p50 mélange les deux phases.

```
  HTTP  timing
    TTFB       :  28.3 ms  ← traitement serveur
    Transfert  :   9.7 ms  ← download du contenu
    Total p50  :  38.0 ms
```

---

### 2. Monitoring continu (`--interval`)
**Inspiré de** `mtr`

Relancer les mesures toutes les N secondes avec détection automatique de dégradation.

```bash
ping-tool --interval 60   # mesure toutes les 60 secondes
```

Afficher une alerte si un percentile dépasse un seuil ou s'écarte significativement
de la mesure précédente : *"p50 : 45ms → 89ms (+98%) depuis 14h32"*.

---

### 3. Validation de la réponse HTTP
**Inspiré de** `blackbox_exporter`

Vérifier le contenu de la réponse en plus de la latence :
- Code de statut attendu (alerter si 5xx ou 4xx)
- Présence d'une chaîne dans le body (`assert_body_contains`)
- Header obligatoire (`assert_header`)

```yaml
sites:
  - url: https://api.exemple.com/health
    assert:
      status_code: 200
      body_contains: "ok"
      header: "Content-Type: application/json"
```

---

### 4. Comparaison avec une baseline CSV
**Inspiré des outils de CI/CD performance**

Charger le CSV d'une exécution précédente et comparer automatiquement :

```
  Comparaison vs baseline (2026-04-20)
    HTTP p50  :  38 ms → 89 ms   +134%  ⚠ régression
    HTTP p95  : 145 ms → 152 ms    +5%  ✓ stable
    DNS       :   8 ms →   7 ms    -12%  ✓ amélioration
```

Utile pour détecter des régressions de performance entre déploiements.

---

## Priorité moyenne — différenciation

### 5. Export Prometheus
**Inspiré de** `blackbox_exporter`, `vegeta`

Générer un fichier `.prom` ou exposer un endpoint `/metrics` pour intégration
dans Grafana/Prometheus sans redéveloppement.

```bash
ping-tool --prometheus-out metrics.prom
```

```
# HELP ping_tool_http_p50_ms HTTP latency p50
# TYPE ping_tool_http_p50_ms gauge
ping_tool_http_p50_ms{url="https://google.com"} 38.0
```

---

### 6. Analyse de la chaîne de redirections
**Inspiré de** `curl -L -v`

Chaque redirect HTTP coûte un aller-retour complet. Afficher la chaîne avec
la latence de chaque saut :

```
  Redirections
    http://google.com      →  301  +23 ms
    https://google.com     →  301  +18 ms
    https://www.google.com →  200  destination
    Coût total redirects   :  41 ms
```

---

### 7. Informations TLS avancées
**Inspiré de** `blackbox_exporter`, `openssl s_client`

Compléter la mesure TLS avec des informations qualitatives :
- Version TLS négociée (1.2 vs 1.3 — TLS 1.3 économise un aller-retour)
- Cipher suite
- Expiration du certificat (dans X jours)

```
  TLS   (handshake, ×1)  :  31 ms  TLS 1.3  AES-256-GCM
  Certificat             :  expire dans 87 jours
```

---

### 8. Détection CDN et cache
**Inspiré de** `curl -I`, outils d'audit web

Lire les headers de réponse pour déterminer si la réponse vient d'un cache
CDN ou du serveur d'origine — explique souvent une latence anormalement basse ou haute.

```
  Cache  →  HIT  Cloudflare (CDN PoP: YUL)   Age: 42s
```

Headers analysés : `X-Cache`, `CF-Ray`, `X-Served-By`, `Age`, `Via`.

---

### 9. Graphique TUI temps réel
**Inspiré de** `gping`

Afficher un histogramme ASCII mis à jour en direct pendant la mesure,
plutôt qu'attendre la fin de toutes les itérations.

```
https://google.com  ▁▂▃▂▁▄▂▁▃▅▂▁▂▃  p50: 38ms
https://github.com  ▂▄▃▅▄▃▆▄▃▂▄▅▃▄  p50: 145ms
```

---

## Priorité basse — cas avancés

### 10. Requêtes concurrentes (`--concurrent`)
**Inspiré de** `hey`, `k6`

Simuler N utilisateurs simultanés pour observer la dégradation de latence sous charge.
Différent des mesures séquentielles actuelles.

```bash
ping-tool --concurrent 10 --rate 50/s -n 1000
```

---

### 11. Comparaison IPv4 vs IPv6
Sur les sites dual-stack, mesurer les deux chemins réseau et afficher le delta.
Utile pour valider la configuration réseau et le routage.

```
  IPv4  p50 :  38 ms
  IPv6  p50 :  31 ms  (-7 ms)
```

---

### 12. Profils multi-environnements ✓ *implémenté — option `--config-file`*
Sélectionner un fichier de configuration différent selon l'environnement,
pour comparer facilement staging vs production.

```bash
ping-tool --config-file prod.yaml
ping-tool --config-file staging.yaml
```

---

### 14. Détection des redirections HTTP dans les assertions

**Contexte :** L'assertion `status_code` actuelle suit automatiquement les redirections
(`urllib` suit les 301/302 par défaut) et retourne le code final. Il n'est donc pas possible
de vérifier qu'une URL `http://` redirige bien vers `https://`.

Ajouter un mode sans suivi de redirections pour les assertions :

```yaml
assert:
  status_code: 301          # vérifie la redirection elle-même
  location: "https://"     # vérifie le header Location
  follow_redirects: false   # désactive le suivi automatique
```

Utile pour valider que la politique HTTPS est bien en place (HSTS, redirection forcée).

---

### 13. Webhook d'alerte SLO
Envoyer une notification HTTP (Slack, PagerDuty, Teams, webhook générique)
quand un SLO est violé. Transforme ping-tool en sonde d'alerte légère.

```yaml
alerting:
  webhook: https://hooks.slack.com/services/xxx
  on: slo_violation
```

---

## Ce que ping-tool fait déjà mieux que la plupart des outils comparés

| Fonctionnalité | ping-tool | hey | mtr | blackbox_exporter | curl |
|---|:---:|:---:|:---:|:---:|:---:|
| Décomposition ICMP / TCP / TLS / HTTP | ✓ | — | partiel | partiel | partiel |
| SLOs par site avec seuils configurables | ✓ | — | — | ✓ | — |
| HdrHistogram (précision percentiles) | ✓ | ✓ | — | — | — |
| Indicateur de stabilité p99/p50 | ✓ | — | — | — | — |
| Estimation keep-alive vs connexion froide | ✓ | — | — | — | — |
| Multi-langue (FR/EN) | ✓ | — | — | — | — |
| Configuration YAML avec SLOs par site | ✓ | — | — | ✓ | — |
| Validation HTTP (status, body, header) | ✓ | — | — | ✓ | — |
| Profils multi-fichiers (`--config-file`) | ✓ | — | — | — | — |
| Indicateur de hops réseau (traceroute) | ✓ | — | ✓ | — | — |
