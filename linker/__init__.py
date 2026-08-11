"""C-IED Incident Link Analysis — offline entity extraction, recognition & matching."""
from .ingest import load_incidents
from .extract import FeatureExtractor
from .match import Matcher
from .cluster import Clusterer

__version__ = "0.1.0"
__all__ = ["load_incidents", "FeatureExtractor", "Matcher", "Clusterer"]
