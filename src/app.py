"""Streamlit entry point. Run from any directory with python -m streamlit run."""
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / '.env')

from src.observability import configure_logging
from src.ui.application import run

configure_logging()
run()
