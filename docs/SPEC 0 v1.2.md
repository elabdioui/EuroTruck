SPEC 0 AMENDMENT v1.2 — Authorized frozen exceptions for SPEC 1

Amends SPEC 0 v1.1. Supersedes any prior freeze on the two files below, scoped strictly to SPEC 1 changes.

Exceptions autorisées
Exception 1 — detector/mt5_client.py

SPEC 1 est autorisée à modifier ce fichier pour :

Ajouter la résolution PIP = symbol_info.point × 10 post-connexion MT5
Ajouter le log de confirmation PIP resolved: {value}
Rien d'autre.

Exception 2 — detector/order_block.py

SPEC 1 est autorisée à remplacer le literal 0.10 (non-PIP, comparaison interne) par 0.1 pour satisfaire AC2.

Un seul remplacement cosmétique, pas de refactor logique.

Ce qui reste gelé
Tout le reste de la liste FROZEN SPEC 0 §2.2 demeure intact.