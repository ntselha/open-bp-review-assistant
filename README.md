# Open BP Review Assistant

An open-source, device-agnostic prototype that turns a weekly home blood pressure monitoring file into a staff-reviewed care-team summary and a template-based follow-up message draft. It is aimed at under-resourced programs. Final project for EPID 695/895, Agentic AI in Healthcare and Public Health.

## Current contents

- `readability_node.py`: Readability check node. Scores draft patient messages with the Flesch-Kincaid Grade Level (textstat) and flags drafts above the target grade for staff review. Drafts are never blocked or rewritten.
- `READABILITY_NODE_CONTRACT.md`: The node's interface contract.
- `test_flesch_kincaid_grade_level.py`: Session 6 unit tests for the readability protocol.

## Run the tests

    pip install -r requirements.txt
    python -m pytest -v

All test data is synthetic. No real patient data is included.