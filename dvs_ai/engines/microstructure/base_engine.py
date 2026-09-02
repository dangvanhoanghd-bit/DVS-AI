from abc import ABC, abstractmethod
import pandas as pd
from .base import MicrostructureEvidence
class EvidenceEngine(ABC):
    @abstractmethod
    def analyze(self, ohlcv: pd.DataFrame, context: dict)->MicrostructureEvidence: raise NotImplementedError
