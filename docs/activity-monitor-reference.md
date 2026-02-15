# Activity Monitor — Prediction Analytics

Reference doc for CLAUDE.md. Four analytical methods computed on each 15-min flush and cached in `activity_summary`.

| Method | What it does | Cold-start requirement |
|--------|-------------|----------------------|
| `_event_sequence_prediction` | Frequency-based next-domain model from 5-domain n-grams | 6+ events in window history |
| `_detect_activity_patterns` | Frequent 3-domain trigrams (3+ occurrences in 24h) | 3+ recurring sequences |
| `_predict_next_arrival` | Day-of-week historical occupancy transition averages | Occupancy transitions in history |
| `_detect_activity_anomalies` | Current event rate vs hourly historical average (flags >2x) | Hourly average data |
