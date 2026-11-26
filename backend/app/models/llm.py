"""Pydantic models for structured LLM output (pedagogical debunking + test synthesis)."""
from __future__ import annotations

from typing import Literal

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


class SimulatedTestCase(BaseModel):
    """A model prediction, never a report of executed code."""

    name: str = Field(..., min_length=1, description="Matching test name in test_case_names and test_code")
    category: Literal['happy_path', 'transformation', 'edge_case', 'boundary']
    input: str = Field(..., min_length=1, description="Concrete inputs and any required setup")
    expected_output: str = Field(..., min_length=1, description="Expected result or exception, grounded in the source")
    predicted_output: str = Field(..., min_length=1, description="Result predicted by reasoning through the source, without executing it")
    steps: list[str] = Field(..., min_length=1, max_length=12,
                             description="Ordered trace with function names, branches, intermediate values, and final result")
    rationale: str = Field(..., min_length=1, description="Why this case matters; state assumptions and uncertainty")


class GeneratedTestSuite(BaseModel):
    """Runnable tests and illustrative model simulations for a function or full source flow."""

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
    purpose: str = Field(..., min_length=1, description="Purpose of the code and behavior this suite checks")
    scenarios: list[SimulatedTestCase] = Field(
        ..., min_length=1, max_length=12,
        description="Model-simulated cases matching the runnable tests, including normal, transformation, and boundary behavior"
    )
