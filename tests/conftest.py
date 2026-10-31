import os

# Tests never call a real LLM or WhatsApp.
os.environ.setdefault("METATRON_LLM_MODE", "offline")
