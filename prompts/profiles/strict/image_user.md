# Image User Prompt

Describe image from markdown lecture notes.

Markdown file: {{markdown_file}}

Nearby heading: {{nearby_heading}}

Return JSON only with keys: detected_type, summary, visible_text, chart_structure, possible_risks, confidence.

Prefer visible facts. If something is ambiguous, name ambiguity instead of guessing. Use short lists. If text is unreadable, say so in possible_risks.
