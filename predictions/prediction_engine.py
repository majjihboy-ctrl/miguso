import math
from scipy.stats import poisson

LEAGUE_AVG_GOALS = 1.4
DIXON_COLES_RHO = -0.13
EMA_ALPHA = 0.12
STRENGTH_MIN = 0.3
STRENGTH_MAX = 3.0
MAX_GOALS = 10


def _clamp(value):
    return max(STRENGTH_MIN, min(STRENGTH_MAX, float(value)))


def tau_correction(x, y, lambda_h, lambda_a, rho):
    if x == 0 and y == 0:
        return 1.0 - lambda_h * lambda_a * rho
    elif x == 1 and y == 0:
        return 1.0 + lambda_h * rho
    elif x == 0 and y == 1:
        return 1.0 + lambda_a * rho
    elif x == 1 and y == 1:
        return 1.0 - rho
    else:
        return 1.0


def predict_match(
    home_attack,
    home_defense,
    away_attack,
    away_defense,
    home_advantage=1.15,
    league_avg=LEAGUE_AVG_GOALS,
    rho=DIXON_COLES_RHO,
    max_goals=MAX_GOALS,
):
    lambda_h = league_avg * home_attack * away_defense * home_advantage
    lambda_a = league_avg * away_attack * home_defense

    matrix = {}
    total_prob = 0.0

    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            base = poisson.pmf(i, lambda_h) * poisson.pmf(j, lambda_a)
            tau = tau_correction(i, j, lambda_h, lambda_a, rho)
            prob = base * tau
            matrix[(i, j)] = float(prob)
            total_prob += prob

    for key in matrix:
        matrix[key] = float(matrix[key] / total_prob)

    home_win_prob = sum(
        matrix[(i, j)] for i in range(max_goals + 1) for j in range(max_goals + 1) if i > j
    )
    draw_prob = sum(
        matrix[(i, j)] for i in range(max_goals + 1) for j in range(max_goals + 1) if i == j
    )
    away_win_prob = sum(
        matrix[(i, j)] for i in range(max_goals + 1) for j in range(max_goals + 1) if i < j
    )

    exp_home = sum(
        i * matrix[(i, j)] for i in range(max_goals + 1) for j in range(max_goals + 1)
    )
    exp_away = sum(
        j * matrix[(i, j)] for i in range(max_goals + 1) for j in range(max_goals + 1)
    )

    return {
        "home_win_prob": float(home_win_prob),
        "draw_prob": float(draw_prob),
        "away_win_prob": float(away_win_prob),
        "expected_home_goals": float(exp_home),
        "expected_away_goals": float(exp_away),
        "scoreline_matrix": matrix,
    }


def update_team_strengths(
    home_team,
    away_team,
    home_score,
    away_score,
    league_avg=LEAGUE_AVG_GOALS,
    alpha=EMA_ALPHA,
):
    home_attack = float(home_team["attack_strength"])
    home_defense = float(home_team["defense_strength"])
    away_attack = float(away_team["attack_strength"])
    away_defense = float(away_team["defense_strength"])
    home_adv = float(home_team.get("home_advantage", 1.15))

    safe_league = max(league_avg, 0.1)
    safe_away_att = max(away_attack, 0.1)
    safe_away_def = max(away_defense, 0.1)
    safe_home_def = max(home_defense, 0.1)
    safe_home_att = max(home_attack, 0.1)
    safe_home_adv = max(home_adv, 0.1)

    implied_home_attack = home_score / (safe_league * safe_away_def * safe_home_adv)
    implied_home_defense = away_score / (safe_league * safe_away_att)
    implied_away_attack = away_score / (safe_league * safe_home_def)
    implied_away_defense = home_score / (safe_league * safe_home_att)

    new_home_attack = (1 - alpha) * home_attack + alpha * implied_home_attack
    new_home_defense = (1 - alpha) * home_defense + alpha * implied_home_defense
    new_away_attack = (1 - alpha) * away_attack + alpha * implied_away_attack
    new_away_defense = (1 - alpha) * away_defense + alpha * implied_away_defense

    return {
        "home_attack": _clamp(new_home_attack),
        "home_defense": _clamp(new_home_defense),
        "away_attack": _clamp(new_away_attack),
        "away_defense": _clamp(new_away_defense),
    }


def score_prediction(predicted_home, predicted_away, actual_home, actual_away):
    if predicted_home == actual_home and predicted_away == actual_away:
        return 5
    pred_diff = predicted_home - predicted_away
    actual_diff = actual_home - actual_away
    if pred_diff == actual_diff:
        return 3
    pred_outcome = 1 if pred_diff > 0 else (-1 if pred_diff < 0 else 0)
    actual_outcome = 1 if actual_diff > 0 else (-1 if actual_diff < 0 else 0)
    if pred_outcome == actual_outcome:
        return 1
    return 0