# Tool choices

**FastAPI.** You chose Python and FastAPI. One process can check the form and run the three checks at the same time. We did not pick Flask, because those three simultaneous checks would need extra concurrency work on a sync framework. Customer concern: during the last 90 minutes, the console should keep taking reports without a second application server to run.

**Jinja2 pages served by FastAPI.** The form, the errors, and the step cards are server-rendered pages, so the start command stays one process. We did not pick React, because it adds a build and a second toolchain. Customer concern: the Flight Director should be able to open the console without a frontend build.

**SQLite.** You chose SQLite. Reports remain on disk after the process stops, and the start command does not start a database server. We did not pick PostgreSQL, because that is a separate service for a single console. Customer concern: if the console is restarted during the count, reports already filed must still be there.

**Claude Opus 5 on Azure AI Foundry.** It is the only model you currently have access to. We did not pick a smaller hosted model or a model running on the console machine, because you do not have access to those. Customer concern: one report can take a sort, three checks, and up to three draft-and-review rounds. That latency and cost sit on a live countdown, and a Foundry outage stops new briefings even though the limit check is local.
