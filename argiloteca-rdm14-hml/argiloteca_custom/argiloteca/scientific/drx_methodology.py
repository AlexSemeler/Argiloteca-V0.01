"""Read-only presentation of the owner's revised methodology document."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_methodology():
    """Load packaged source text and clearly separate bilingual reading summaries."""
    path = Path(__file__).resolve().parents[1] / 'data' / 'drx_methodology_20261024.json'
    return json.loads(path.read_text(encoding='utf-8'))
