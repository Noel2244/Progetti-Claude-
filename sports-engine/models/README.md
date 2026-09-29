# models/ (not committed)

`calibration/<model>.json` - live calibrators written by the latest backtest (JSON, never
pickle): selection method, validation scores, fitted period, run id, dataset fingerprint.
Model parameters themselves are refitted point-in-time at every run; the model registry
(champion/challenger) lives in the SQLite database.
