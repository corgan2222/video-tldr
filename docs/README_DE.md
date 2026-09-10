# video-tltr

_[English version](../README.md)_

Zu lang zum Lesen? Eine Erweiterung für Firefox und Chrome mit einem
lokalen Dienst, die aus dem YouTube-Video im aktiven Tab eine
Zusammenfassung mit Bildern macht. Das Repository behält seinen alten
Namen, corganshelper.

## Was es kann

- **Video-Zusammenfassung.** Das Symbol in der Werkzeugleiste öffnet ein
  kleines Fenster mit zwei Knöpfen. „Fast" und „Thorough" übergeben das
  Video an einen lokalen Dienst. Der holt Titel, Beschreibung, Kapitel
  und Untertitel, transkribiert den Ton, wenn Untertitel fehlen, lässt
  ein Sprachmodell den Inhalt einordnen und zusammenfassen, zieht
  Standbilder an den sehenswerten Stellen, liest die
  Installationsschritte aus verlinkten GitHub-Repositories und schreibt
  das Ergebnis als Markdown, als Notiz in einen Obsidian-Vault, als PDF
  und als Word-Datei. Das Fenster zeigt jeden Schritt mit seinen
  Sekunden, eine Schätzung der Restzeit aus Ihren früheren Läufen, das
  Dienst-Log und einen Knopf, der das Ergebnis öffnet. Das Sprachmodell
  läuft über die Claude-Code-CLI, die API von Anthropic oder OpenAI, LM
  Studio oder Ollama; die Transkription über Whisper, Parakeet, Canary
  oder OpenAI. Die Wahl steht in den Einstellungen der Erweiterung, die
  auch zeigen, was jedes Modell auf Ihrem Rechner gebraucht hat.
- **Open all links.** Text markieren, im Kontextmenü „Open all links"
  wählen, und jeder Link in der Markierung öffnet sich als Tab in einem
  neuen Fenster: YouTube-Weiterleitungen ausgepackt, Sponsor- und
  Affiliate-Hosts ausgelassen, einmal geöffnete Links beim nächsten Mal
  übersprungen.

## Installation

Bis zum ersten Release aus dem Quelltext bauen:

```
npm ci
npm run build
```

`dist/` in Firefox als temporäres Add-on laden (`about:debugging`, „Dieser
Firefox") oder in Chrome als entpackte Erweiterung (`chrome://extensions`,
Entwicklermodus). Die Video-Zusammenfassung braucht den lokalen Dienst aus
[`service/`](../service/README.md); dessen README beschreibt Einrichtung
und Modellwahl.

## Benutzung

1. Dienst starten: `cd service && uv run video-tltr serve`. Er druckt ein
   Token.
2. Auf das Symbol klicken; ohne Token öffnet es die Einstellungen. Token
   eintragen, „Connect" drücken, Sprache, Ausgaben und Modell wählen,
   „Save".
3. Ein YouTube-Video öffnen, auf das Symbol klicken, „Fast" oder
   „Thorough" drücken. Das Fenster zeigt die Schritte, während sie
   laufen; eine Benachrichtigung meldet, wenn die Zusammenfassung fertig
   ist, und ein Klick darauf öffnet die Notiz.
4. Ohne Browser: `uv run video-tltr run <url>` macht dasselbe von der
   Kommandozeile.

---

Diese Datei ist für Nutzer geschrieben. Beitragende lesen die englischen
Dateien: [CONTRIBUTING.md](../CONTRIBUTING.md), Lizenz in
[LICENSE](../LICENSE).
