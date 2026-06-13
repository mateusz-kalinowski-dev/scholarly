"""Compat for RAGAS + langchain-community 0.4+ (Vertex AI moved out of community)."""

from __future__ import annotations

import sys
import types


def patch_vertexai_chat_model() -> None:
    """Register langchain_community.chat_models.vertexai for RAGAS import side-effects."""
    module_name = "langchain_community.chat_models.vertexai"
    if module_name in sys.modules:
        return
    try:
        from langchain_community.chat_models.vertexai import ChatVertexAI  # noqa: F401
    except ModuleNotFoundError:
        from langchain_google_vertexai import ChatVertexAI as _ChatVertexAI

        shim = types.ModuleType(module_name)
        shim.ChatVertexAI = _ChatVertexAI
        sys.modules[module_name] = shim


patch_vertexai_chat_model()
