# Decomposition Evaluation Report

- **LLM mode:** `mock`  |  **model:** `mock`
- **Modules analysed:** 14  |  **dependency edges:** 49
- **Clustering:** idf-greedy-modularity(hub-aware, res=0.8) + llm-refine
- **Predicted services:** 7  |  **ground-truth services:** 7


## 1. Headline — proposed (LLM-refined) decomposition

| Metric | Value | Meaning |
|---|---|---|
| Adjusted Rand Index | **0.839** | agreement vs ground truth, chance-corrected (1 = perfect, 0 = random) |
| Normalized Mutual Information | 0.936 | shared information between partitions |
| Homogeneity / Completeness | 0.945 / 0.926 | each service pure / each domain intact |
| V-measure | 0.936 | harmonic mean of the two |
| Pairwise Precision / Recall / F1 | 0.900 / 0.818 / 0.857 | co-membership pair accuracy |
| Macro / Weighted F1 (per-service) | 0.924 / 0.933 | after optimal service alignment |
| Modularity Q | -0.097 | structural quality of the partition on the dependency graph |
| Inter-service cut ratio | 0.818 | fraction of dependency weight crossing service boundaries (lower = cleaner cut) |

## 2. Per-service precision / recall / F1

Predicted services are optimally matched to ground-truth services (Hungarian algorithm).

| Ground-truth service | Matched prediction | TP | Pred size | Truth size | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| Catalog | Catalog | 2 | 2 | 2 | 1.000 | 1.000 | 1.000 |
| Inventory | Inventory | 1 | 2 | 1 | 0.500 | 1.000 | 0.667 |
| Notifications | Notifications | 1 | 1 | 1 | 1.000 | 1.000 | 1.000 |
| Orders | Orders | 2 | 2 | 3 | 1.000 | 0.667 | 0.800 |
| Payments | Payments | 1 | 1 | 1 | 1.000 | 1.000 | 1.000 |
| Platform | Platform | 4 | 4 | 4 | 1.000 | 1.000 | 1.000 |
| Users/Auth | Users/Auth | 2 | 2 | 2 | 1.000 | 1.000 | 1.000 |
| **Macro avg** |  |  |  |  | 0.929 | 0.952 | 0.924 |

## 3. Cohesion & coupling (per proposed service)

Ca = afferent coupling (incoming), Ce = efferent coupling (outgoing), Instability I = Ce/(Ca+Ce), Cohesion = intra-service / total traffic.

| Service | Modules | Internal | Ca | Ce | Instability | Cohesion |
|---|---|---|---|---|---|---|
| Catalog | 2 | 2.000 | 10.000 | 16.000 | 0.615 | 0.071 |
| Inventory | 2 | 3.000 | 8.000 | 10.000 | 0.556 | 0.143 |
| Notifications | 1 | 0.000 | 8.000 | 13.000 | 0.619 | 0.000 |
| Orders | 2 | 2.000 | 4.000 | 44.000 | 0.917 | 0.040 |
| Payments | 1 | 0.000 | 4.000 | 14.000 | 0.778 | 0.000 |
| Platform | 4 | 21.000 | 95.000 | 20.000 | 0.174 | 0.154 |
| Users/Auth | 2 | 2.000 | 6.000 | 18.000 | 0.750 | 0.077 |

## 4. Baseline battery — is the metric suite well-calibrated?

The same metrics are computed for reference partitions. A good suite must rank a random or trivial partition near zero and the true structure near one. This is what makes the headline numbers trustworthy rather than lucky.

| Partition | #Services | ARI | NMI | Macro-F1 | Modularity Q | Cut ratio |
|---|---|---|---|---|---|---|
| `refined` ⭐ | 7 | 0.839 | 0.936 | 0.924 | -0.097 | 0.818 |
| `algorithmic` | 4 | 0.169 | 0.582 | 0.403 | -0.041 | 0.709 |
| `louvain` | 2 | -0.050 | 0.208 | 0.121 | 0.107 | 0.315 |
| `greedy_raw` | 2 | -0.050 | 0.208 | 0.121 | 0.107 | 0.315 |
| `ground_truth` | 7 | 1.000 | 1.000 | 1.000 | -0.121 | 0.836 |
| `single_service` | 1 | 0.000 | 0.000 | 0.063 | 0.000 | 0.000 |
| `per_module` | 14 | 0.000 | 0.814 | 0.748 | -0.103 | 1.000 |
| `random (mean of 50)` | 6 | 0.021 ± 0.112 | 0.583 | 0.460 | -0.082 | 0.835 |

## 5. Interpretation

- **Structural clustering alone** reaches ARI 0.17: unsupervised modularity maximisation under-segments because bounded contexts in the monolith are genuinely coupled (checkout imports discovery, inventory, payments, users and notifications).
- **Adding the semantic (LLM/mock) refinement** lifts ARI to 0.84 (Δ = +0.67): domain reasoning splits the coupled clusters back into their bounded contexts and consolidates the shared kernel into Platform. It is strong but **not perfect** — the deliberately ambiguous `logistics` module (Orders by ground truth, but pure warehouse-stock behaviour) is filed under Inventory, a defensible boundary error.
- The metric suite is **calibrated**: over 50 random partitions the mean ARI is 0.02 ± 0.11 while the true structure scores 1.00, so the headline number reflects real agreement, not metric inflation.
- **Why ARI leads, not NMI**: NMI is biased upward by fine partitions — the `per_module` baseline scores NMI 0.81 but ARI 0.00. ARI is chance-corrected and robust to the number of clusters, so it is the primary agreement metric here.
- **Modularity is the wrong objective for this problem**: the ground-truth partition itself scores Q = -0.12 on the raw graph, because the shared kernel and cross-context orchestration couple every domain. A partition that *maximised* modularity (see `louvain`/`greedy_raw`) actively mis-groups domains — which is precisely why structural clustering must be combined with domain semantics rather than trusted alone.
- **Cohesion/coupling**: the proposed cut leaves 82% of dependency weight crossing service boundaries. Instability I confirms the roles: Orders is the most unstable service (an orchestrator that depends on everything) while Platform is the most stable (a shared kernel depended upon by everything) — exactly the seams a strangler-fig migration addresses first.
