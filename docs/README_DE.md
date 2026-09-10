# corganshelper

_[English version](../README.md)_

Eine Manifest-V3-Erweiterung für Firefox und Chrome, dazu ein lokaler
Dienst, der aus einem YouTube-Video eine Zusammenfassung macht.

## Was es kann

- **Video-Zusammenfassung.** Ein Klick auf das Symbol in der Werkzeugleiste
  übergibt das YouTube-Video im aktiven Tab an einen lokalen Dienst. Der
  holt Titel, Beschreibung, Kapitel und Untertitel, transkribiert den Ton,
  wenn Untertitel fehlen, lässt ein Sprachmodell den Inhalt einordnen und
  zusammenfassen, zieht Standbilder an den sehenswerten Stellen, liest die
  Installationsschritte aus verlinkten GitHub-Repositories und schreibt das
  Ergebnis als Markdown, als Notiz in einen Obsidian-Vault, als PDF und als
  Word-Datei. Das Sprachmodell läuft über die Claude-Code-CLI, die API von
  Anthropic oder OpenAI, LM Studio oder Ollama; die Transkription über
  Whisper, Parakeet, Canary oder OpenAI. Die Wahl steht in den Optionen der
  Erweiterung.
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

1. Dienst starten: `cd service && uv run corganshelper serve`. Er druckt
   ein Token.
2. Optionen der Erweiterung öffnen, Dienst-URL und Token eintragen,
   „Connect" drücken, Sprache, Ausgaben und Modell wählen, „Save".
3. Ein YouTube-Video öffnen und auf das Symbol klicken. Das Badge zeigt den
   Schritt, an dem der Dienst gerade ist; eine Benachrichtigung meldet,
   wenn die Zusammenfassung fertig ist, und ein Klick darauf öffnet die
   Notiz.
4. Ohne Browser: `uv run corganshelper run <url>` macht dasselbe von der
   Kommandozeile.

---

Diese Datei ist für Nutzer geschrieben. Beitragende lesen die englischen
Dateien: [CONTRIBUTING.md](../CONTRIBUTING.md), Lizenz in
[LICENSE](../LICENSE).
