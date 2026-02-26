"""Model serialization — pickle save/load for sklearn models."""

import logging
import pickle
from pathlib import Path

logger = logging.getLogger(__name__)


class ModelIO:
    """Pickle-based model persistence."""

    def __init__(self, models_dir: Path):
        self.models_dir = models_dir

    def save_model(self, model, name: str, metadata: dict | None = None) -> Path:
        """Save a trained model to disk."""
        self.models_dir.mkdir(parents=True, exist_ok=True)
        path = self.models_dir / f"{name}.pkl"
        with open(path, "wb") as f:
            pickle.dump({"model": model, "metadata": metadata or {}}, f)
        return path

    def load_model(self, name: str):
        """Load a saved model. Returns (model, metadata) or (None, None) if not found."""
        path = self.models_dir / f"{name}.pkl"
        if not path.is_file():
            return None, None
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            if isinstance(data, dict) and "model" in data:
                model = data["model"]
                metadata = data.get("metadata", {})
            else:
                # Legacy format: the data itself is the model object
                model = data
                metadata = {}

            # Validate the loaded object has the expected ML interface
            if not hasattr(model, "predict"):
                logger.error(
                    "model_io: loaded object from %s has no .predict() method — type: %s",
                    path,
                    type(model).__name__,
                )
                return None, None

            return model, metadata
        except Exception:
            logger.warning("Failed to load model %s from %s", name, path, exc_info=True)
            return None, None

    def list_models(self) -> list[str]:
        """List available model names."""
        if not self.models_dir.is_dir():
            return []
        return [f.stem for f in sorted(self.models_dir.glob("*.pkl"))]

    def model_exists(self, name: str) -> bool:
        """Check if a model file exists."""
        return (self.models_dir / f"{name}.pkl").is_file()
