import pytest

from rag.db import Collection, EmbeddingModelMismatch, check_binding

C = Collection("mpep", "vs_1", "embed/granite-embedding-english-r2", 768, "src", "rev", "")


def test_binding_accepts_same_model() -> None:
    check_binding(C, "embed/granite-embedding-english-r2", 768)


@pytest.mark.parametrize(
    ("model", "dim"), [("embed/other", 768), ("embed/granite-embedding-english-r2", 384)]
)
def test_binding_rejects_other_model_or_dimension(model: str, dim: int) -> None:
    with pytest.raises(EmbeddingModelMismatch):
        check_binding(C, model, dim)
