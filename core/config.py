import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "claimbridge.db"
UPLOAD_DIR = ROOT / "data" / "uploads"
FIXTURES_DIR = ROOT / "data" / "fixtures"
POLICIES_PATH = ROOT / "data" / "policies" / "policies.json"

LLM_MODE = os.getenv("CLAIMBRIDGE_LLM_MODE", "template")

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
