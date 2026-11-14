# big-bet-videos

Technik hinter dem YouTube-Kanal „Quiz um Fünf“ (@quizumfuenf): Dieses Repository lädt die fertigen Folgen zu YouTube hoch
und führt das Fragen-Archiv, damit keine Frage zweimal gesendet wird.

- `queue/` – Upload-Aufträge (eine Datei je Folge). Ein neuer Auftrag startet den Workflow „YouTube-Upload“.
- `results/` – Ergebnis jedes Auftrags (Link zum Video oder der Grund eines Fehlschlags).
- `archiv/` – das Fragen-Archiv: jede gesendete Frage und Behauptung (`qz_NNN.json`), lesbar in
  [archiv/UEBERSICHT.md](archiv/UEBERSICHT.md), dazu der Themen-Vorrat (`vorrat.json`), aus dem neue Folgen ihre Themen ziehen.
- `tools/quiz_archiv.py` – vergleicht jede neue Folge mit dem Archiv (auch umformulierte Fragen und Wahr-oder-falsch-Behauptungen).
- `tools/yt_queue.py` – lädt hoch. Ohne Archiv-Eintrag und bestandene Prüfung wird nichts hochgeladen.
- `docs/` – Startseite, Datenschutz und Nutzungsbedingungen (GitHub Pages).
- Branches `handoff-…` – Übergabe der Videodateien; sie werden nach dem Upload entfernt.

Die Zugangsdaten zum Kanal liegen ausschließlich als verschlüsselte Secrets in den Repository-Einstellungen, nie in einer Datei.
