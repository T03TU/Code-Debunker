"""Pydantic models for structured LLM output (pedagogical debunking + test synthesis)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PrerequisiteConcept(BaseModel):
    name: str = Field(..., description="Name of the programming concept")
    explanation: str = Field(..., description="Concise explanation of how it applies here")


class DebunkResponse(BaseModel):
    """Structured 5-part pedagogical breakdown for Feature C."""

    language_identification: str = Field(
        ..., description="Detected programming language and runtime paradigm (Section 1)"
    )
    feynman_explanation: str = Field(
        ..., description="Jargon-free real-world analogy explaining intent and control flow (Section 2)"
    )
    annotated_code: str = Field(
        ..., description="Exact original selected callable with a mandatory function docstring or JSDoc and inline comments inserted. Never refactor or change executable lines (Section 3)."
    )
    simulated_walkthrough: str = Field(
        ..., description="Concrete sample input, step-by-step state trace, and final output (Section 4)"
    )
    prerequisite_concepts: list[PrerequisiteConcept] = Field(
        ..., min_length=3, max_length=5,
        description="3-5 foundational programming patterns used in the code (Section 5)"
    )


class GeneratedTestSuite(BaseModel):
    """Synthesized unit test suite for a callable from the JSON IR."""

    language: str = Field(..., description="Test framework language: 'python' or 'typescript'")
    framework: str = Field(..., description="Test framework: 'pytest' or 'jest'")
    test_code: str = Field(
        ..., description="Complete self-contained test file with happy-path, edge-case, and boundary tests"
    )
    mock_summary: str = Field(
        ..., description="Description of all stubbed/mocked third-party and unresolved dependencies"
    )
    test_case_names: list[str] = Field(
        default_factory=list,
        description="Names of all individual test functions defined in test_code"
    )
