from .prediction_engine import predict_match


def refresh_match_prediction(match):
    """Run the Poisson engine on a Match and cache the results."""
    result = predict_match(
        match.home_team.attack_strength,
        match.home_team.defense_strength,
        match.away_team.attack_strength,
        match.away_team.defense_strength,
        match.home_team.home_advantage,
    )
    match.pred_home_goals = result["expected_home_goals"]
    match.pred_away_goals = result["expected_away_goals"]
    match.pred_home_win = result["home_win_prob"]
    match.pred_draw = result["draw_prob"]
    match.pred_away_win = result["away_win_prob"]
    match.save()