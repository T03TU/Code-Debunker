---
name: pedagogical-debunking
description: Generates a structured 5-part pedagogical breakdown of a function or code snippet (Language ID, Feynman analogy, Google-style docstrings + inline comments, simulated execution walkthrough, and prerequisite concepts).
---

# Pedagogical Code Debunking Skill

## Instructions
When explaining or debunking a target function grounded in a JSON IR slice, output these exact five sections:

1. **Language Identification:** State the detected programming language and runtime paradigm.
2. **Feynman Explanation:** Explain the overarching intent and control flow using a concrete, jargon-free real-world analogy that accurately maps every branch, filter, and loop.
3. **Annotated Code:** Return the complete, runnable code enriched with:
   - A comprehensive **Google-style docstring** (or JSDoc/Javadoc equivalent) documenting every parameter in `Args:` (marking optional arguments and defaults), every nested key or tuple element in `Returns:`, and exceptions in `Raises:`. Never leave a summary-only docstring.
   - Step-by-step inline comments explaining non-obvious idioms, falsy fallbacks, and state mutations.
4. **Simulated Execution Walkthrough:** Provide a realistic sample input matching `parameters[].inferred_shape`, trace variable state changes step-by-step along `edges.data_flows`, and show the exact final output.
5. **Prerequisite Concepts:** List 3–5 foundational programming patterns used in the code with a concise explanation of how each applies here.

## Constraints
- Focus strictly on `target_symbol_id`. Do not alter executable logic.