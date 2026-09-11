"""Claim note annotator: builds the SME answer key (gold data) for claim notes.

Standard library only. Notes stay as .txt files on disk; the app stores
annotations, their exact character positions, and a fingerprint of each note.
"""

PROMPT_VERSION = "copilot-agent-v1"
