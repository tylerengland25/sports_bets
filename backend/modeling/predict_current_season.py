import pandas as pd
import pickle
import numpy as np
from sklearn.preprocessing import StandardScaler

import backend.scraping.Game_Stats
from backend.scraping.Game_Stats import convert_poss
from backend.scraping.odds import scrape_vegas
from backend.modeling.last_five_model import performance, print_performance, exploratory_analysis, predict


def convert_odds(odds):
    if odds < 0:
        odds = odds * -1
        return odds / (100 + odds)
    else:
        return 100 / (100 + odds)


def calc_profit(stake, odds):
    if odds < 0:
        odds = odds * -1
        return stake / (odds / 100)
    else:
        return stake * (odds / 100)


def load_data_classifier():
    """
    Loads data and splits into X and Y training and testing sets
    :return:
    """
    x_df = pd.read_csv("backend/data/current_last_five_games.csv")
    x_df.fillna(0, inplace=True)
    y_df = pd.read_csv("backend/data/current_season_stats.csv")
    odds = pd.read_csv("backend/data/odds/odds.csv")

    df = pd.merge(y_df, x_df,
                  how="left",
                  left_on=["Home", "Week", "Year"],
                  right_on=["team", "week", "year"])

    df = pd.merge(df, x_df,
                  how="left",
                  left_on=["Away", "Week", "Year"],
                  right_on=["team", "week", "year"])

    df = df[(df["Week"] > 5) | (df["Year"] != 2010)]
    df.set_index(["Home", "Away", "Week", "Year"], inplace=True)

    x_cols = []
    for col in df.columns:
        if "poss" in col:
            df[col] = df[col].apply(lambda x: convert_poss(x) if ":" in x else x)
            x_cols.append(col)
        elif col[-4:] in ["_1_x", "_1_y"] \
                and "named" not in col and "opponent" not in col and "season_length" not in col:
            x_cols.append(col)
            df[col] = df[col] * 3
        elif col[-4:] in ["_2_x", "_2_y"] \
                and "named" not in col and "opponent" not in col and "season_length" not in col:
            x_cols.append(col)
            df[col] = df[col] * 3
        elif col[-4:] in ["_3_x", "_3_y"] \
                and "named" not in col and "opponent" not in col and "season_length" not in col:
            x_cols.append(col)
            df[col] = df[col] * 2

        elif col[-4:] in ["_4_x", "_4_y"] \
                and "named" not in col and "opponent" not in col and "season_length" not in col:
            x_cols.append(col)
            df[col] = df[col] * 2
        elif col[-4:] in ["_5_x", "_5_y"] \
                and "named" not in col and "opponent" not in col and "season_length" not in col:
            x_cols.append(col)
            df[col] = df[col] * 2

    # Standardized X values
    # x_cols = ["3rd_att", "3rd_cmp", "3rd_att_def", "3rd_cmp_def", "4th_att", "4th_cmp", "4th_att_def", "4th_cmp_def",
    #           "cmp", "cmp_def", "poss", "total_y", "total_y_def"]
    x_cols = ["cmp_pct", "cmp_pct_def", "3rd_pct", "3rd_pct_def", "4th_pct", "4th_pct_def", "fg_pct", "yds_per_rush",
              "yds_per_rush_def", "yds_per_att", "yds_per_att_def", "yds_per_ply", "yds_per_ply_def", "poss",
              "pass_yds", "pass_yds_def", "pen_yds", "pen_yds_def", "punts", "punts_def", "rush_yds", "rush_yds_def",
              "sacks", "sacks_def", "score", "score_def", "cmp", "cmp_def", "total_y", "total_y_def", "pts_per_ply",
              "pts_per_ply_def", "punts_per_ply", "punts_per_ply_def", "pts_per_yd", "pts_per_yd_def"]

    final_cols = []
    for col in x_cols:
        for i in range(1, 6):
            final_cols.append(col + "_" + str(i) + "_x")
            final_cols.append(col + "_" + str(i) + "_y")
    X = df[final_cols]
    X.astype(float)
    scaler = StandardScaler()
    X_standardized = pd.DataFrame(scaler.fit_transform(X))
    X_standardized.index = X.index

    # Y values
    df = pd.merge(df, odds.iloc[:, 1:],
                  how="left",
                  left_on=["Home", "Away", "Week", "Year"],
                  right_on=["Home", "Away", "Week", "Year"])
    df.set_index(["Home", "Away", "Week", "Year"], inplace=True)
    df["win_lose"] = df["H_Score"] - df["A_Score"]
    df["win_lose"] = df["win_lose"] > 0
    df["win_lose"] = df["win_lose"].astype(int)
    y = df[["win_lose", "ML_h", "ML_a"]]
    y.index = df.index

    return X_standardized, y


def current_week(cw, unit):
    # Load data
    odds = pd.read_excel("backend/data/odds/nfl odds 2021-22.xlsx")
    X, y = load_data_classifier()
    svm = pickle.load(open("backend/modeling/models/svm.pkl", "rb"))
    # Filter data
    X = X.reset_index()
    X = X[(X["Year"] == 2021) & (X["Week"] == cw)]
    odds = odds[odds["Week"] == cw].drop(["Unnamed: 0"], axis=1).reset_index(drop=True)

    # Predict
    predictions = pd.DataFrame(svm.predict_proba(X.drop(["Home", "Away", "Week", "Year"], axis=1)),
                               columns=["away_predict_prob", "home_predict_prob"])
    # Join vegas odds
    odds = pd.merge(odds, predictions, how="left", left_index=True, right_index=True)

    # Feature engineer probabilities, potential payouts, and divergences
    odds["away_actual_prob"] = odds["ML_a"].apply(lambda x: convert_odds(x))
    odds["home_actual_prob"] = odds["ML_h"].apply(lambda x: convert_odds(x))
    odds["away_divergence"] = odds["away_predict_prob"] - odds["away_actual_prob"]
    odds["home_divergence"] = odds["home_predict_prob"] - odds["home_actual_prob"]

    # Predict outcome
    odds["predict_outcome"] = predict(odds)
    odds = odds.dropna(axis=0)

    # Calculate potential units
    odds["potential_units"] = np.where(odds["predict_outcome"],
                                       odds["ML_h"].apply(lambda x: calc_profit(unit, x) / unit),
                                       odds["ML_a"].apply(lambda x: calc_profit(unit, x) / unit))

    # Format for excel file
    odds["bet"] = np.where(odds["predict_outcome"], odds["Home"], odds["Away"])
    odds["home_predict_prob"] = odds["home_predict_prob"].apply(lambda x: str(round(x * 100)) + "%")
    odds["away_predict_prob"] = odds["away_predict_prob"].apply(lambda x: str(round(x * 100)) + "%")
    odds["home_actual_prob"] = odds["home_actual_prob"].apply(lambda x: str(round(x * 100)) + "%")
    odds["away_actual_prob"] = odds["away_actual_prob"].apply(lambda x: str(round(x * 100)) + "%")
    odds = odds[["Home", "home_predict_prob", "home_actual_prob", "ML_h",
                 "Away", "away_predict_prob", "away_actual_prob", "ML_a",
                 "bet", "potential_units"]]
    odds = odds.rename(columns={"home_predict_prob": "home_predicted_prob", "away_predict_prob": "away_predicted_prob",
                                "home_actual_prob": "home_vegas_prob", "away_actual_prob": "away_vegas_prob"})
    odds["hold"] = odds["ML_h"].apply(lambda x: convert_odds(x)) - odds["ML_a"].apply(lambda x: convert_odds(-1 * x))
    odds["hold"] = odds["hold"].apply(lambda x: str(round(x * 100, 2)) + "%")
    odds.to_csv("backend/data/predictions/Week_" + str(cw) + "_predictions.csv")


def current_season(cw, unit):
    # Load data
    odds = pd.read_excel("backend/data/odds/nfl odds 2021-22.xlsx")
    X, y = load_data_classifier()
    svm = pickle.load(open("backend/modeling/models/svm.pkl", "rb"))
    # Filter data for current season
    y = y.reset_index()
    X = X.reset_index()
    X = X[(X["Year"] == 2021) & (X["Week"] < cw)]
    y = y[(y["Year"] == 2021) & (y["Week"] < cw)]
    # Join odds and data
    y = pd.merge(y.drop(["ML_a", "ML_h"], axis=1), odds.drop(["Unnamed: 0"], axis=1),
                 left_on=["Home", "Away", "Week", "Year"],
                 right_on=["Home", "Away", "Week", "Year"])

    # Predict probabilities and merge with odds
    predictions = pd.DataFrame(svm.predict_proba(X.drop(["Home", "Away", "Week", "Year"], axis=1)),
                               columns=["away_predict_prob", "home_predict_prob"])
    odds = pd.merge(y, predictions, how="left", left_index=True, right_index=True)
    odds = odds.rename(columns={"win_lose": "outcome"})
    # Feature engineer vegas probabilities, potential payouts, and divergences
    odds["away_actual_prob"] = odds["ML_a"].apply(lambda x: convert_odds(x))
    odds["home_actual_prob"] = odds["ML_h"].apply(lambda x: convert_odds(x))
    odds["away_divergence"] = odds["away_predict_prob"] - odds["away_actual_prob"]
    odds["home_divergence"] = odds["home_predict_prob"] - odds["home_actual_prob"]
    odds["potential_payout"] = np.where(odds["outcome"],
                                        odds["ML_h"].apply(lambda x: calc_profit(unit, x)),
                                        odds["ML_a"].apply(lambda x: calc_profit(unit, x)))

    # Exploratory analysis
    exploratory_analysis(odds, unit)

    # Predict outcome
    odds["predict_outcome"] = predict(odds)
    odds = odds.dropna(axis=0)

    # Calculate payout
    odds["potential_payout"] = np.where(odds["predict_outcome"],
                                        odds["ML_h"].apply(lambda x: calc_profit(unit, x)),
                                        odds["ML_a"].apply(lambda x: calc_profit(unit, x)))
    odds["payout"] = np.where(odds["predict_outcome"] == odds["outcome"], odds["potential_payout"], -1 * unit)

    print("Current season performance:")
    by_week = print_performance(odds)
    odds = odds[["Home", "home_predict_prob", "Away", "away_predict_prob", "Week", "ML_h", "ML_a",
                 "predict_outcome", "outcome", "payout"]]
    odds["predict_outcome"] = np.where(odds["predict_outcome"], odds["Home"], odds["Away"])
    odds["outcome"] = np.where(odds["outcome"], odds["Home"], odds["Away"])
    odds["hold"] = odds["ML_h"].apply(lambda x: convert_odds(x)) - odds["ML_a"].apply(lambda x: convert_odds(-1 * x))
    odds.to_csv("backend/data/predictions/season_picks.csv")
    return by_week


if __name__ == '__main__':
    week = 22
    stake = 100
    testing_by_week = performance(stake)
    scrape_vegas(week)
    season_by_week = current_season(week, stake)
    current_week(week, stake)
    weekly = pd.merge(testing_by_week, season_by_week, left_index=True, right_index=True)
    print(weekly)
