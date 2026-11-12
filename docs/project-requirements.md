# Mission Control: Go/No-Go Launch Console

## Problem Statement

Meridian Launch Services is 90 minutes from a launch. Engineers at the consoles send free-text anomaly reports to the Flight Director, such as a valve that behaved oddly or a telemetry link that dropped. The Flight Director has no time to read raw messages and needs a short, clean briefing for each one.

Build Mission Control, a full stack web app where an engineer files a report, a pipeline reads and sorts it, and the Flight Director approves a drafted briefing.

An engineer files a report with a name, a station, three readings (`wind_knots`, `temp_c`, `fuel_pct`), and a free-text note. Your app then does the following:

- Uses a model to sort the report by subsystem and severity.
- Uses plain code, not a model, to check the readings against the launch limits and set the verdict. Wind must be 25 knots or less, temperature 4 C or more, and fuel 98 to 100 percent. Any reading outside its limit makes the verdict `no_go`.
- Sets a brief by time of 5, 15, or 30 minutes for high, medium, or low severity. Any limit violation counts as high.
- Runs three model checks at the same time. One looks for hidden instructions in the note, one for missing details, and one for panic in the tone. A note that tries to give the system instructions must never change the verdict.
- Drafts a briefing with a model and has a second model call review it. It repeats up to three rounds.
- Shows the Flight Director the reports, the briefing, the verdict, the cost, and a trace of each step. Only a person can approve a briefing.

You choose your own tools: back end, front end, database, and models.

## Grading Rubric (100 points)

| Criteria | Points | Evidence |
|---|---:|---|
| The README has one command to start the app and one to run the tests, and both work | 10 | README in the repo and a run of both commands |
| Tool choices explained. Back end, front end, database, and model are each chosen with a specific reason, one rejected alternative, and one customer concern | 10 | A tool choices file in the repo, either a Word document or a .md file |
| Filing reports. The form sends all fields, bad input is rejected with a clear message, and reports are saved and still there after a restart | 10 | Front end source code and a restart test in the repo |
| Launch limits in plain code. The verdict and violations come from code, not from a model, and are correct exactly on each limit and just past it | 15 | Source code and tests in the repo |
| Brief by time. The time follows severity, and any violation counts as high | 10 | Source code and tests in the repo |
| Sorting with a model. The reply uses a structured schema, is checked in code, and an invalid value falls back safely | 10 | Source code and a test in the repo |
| Three checks and hidden instructions. The checks run at the same time, and a note that gives instructions is flagged, sent to review, and never changes the verdict | 10 | Source code and a test with the hidden instruction note in the repo |
| Draft, review, and approval. The loop stops at three rounds, evaluator feedback goes into the next draft, and only a person can approve a pending briefing | 10 | Source code and tests in the repo |
| Trace and cost. The console shows one card per step with its tokens, and the cost of each report is calculated in code | 10 | Front end source code and cost tests in the repo |
| Tests. The tests pass with no network and no API key, because model calls go through one interface with a fake | 5 | Test run output |
| **Total** | **100** | |