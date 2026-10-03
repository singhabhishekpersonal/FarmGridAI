"""Classical ML helpers used by the recommendation engine.

None of these ever produce hard facts: the ranker only reorders candidate
recommendations, and the reference models exist so the system degrades to
deterministic behaviour when no trained artifact is present.
"""


def score_candidates(candidates):
    """Score [0..1] each candidate for ranking.

    Uses a tiny hand-tuned linear model (benefit_max, priority weight).
    The result is used only to order candidates, never to assert truth.
    """
    PRIORITY_WEIGHT = {"critical": 1.0, "high": 0.85, "medium": 0.6, "low": 0.35}

    scores = []
    for candidate in candidates:
        benefit = candidate.get("benefit_max") or 0
        # normalize benefit into 0..1 by capping reference at Rs 5,00,000
        benefit_score = min(1.0, benefit / 500000.0)
        confidence_weight = {"high": 1.0, "medium": 0.7, "low": 0.4}.get(candidate.get("confidence"), 0.4)
        priority = PRIORITY_WEIGHT.get(candidate.get("category_priority", "medium"), 0.6)
        scores.append(round((0.40 * benefit_score) + (0.40 * priority) + (0.20 * confidence_weight), 4))
    return scores