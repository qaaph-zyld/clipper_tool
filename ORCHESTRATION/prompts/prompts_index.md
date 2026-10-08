# Subagent Dispatch Index

**Task**: Eliminate GPT-4o-mini Dependency for Serbian Transcription
**Orchestrator model**: GLM-5.2 Max 1M
**Subagent model**: GLM-5.2 High (default)

| Wave | Agent | Profile | Model | Background | Output |
|------|-------|---------|-------|------------|--------|
| 1 | A | `wave-implementer` | GLM-5.2 High | False | `wave1/agent_a_handoff.md` |
| 1 | — | GATE | **Human approval required** | — | — |
| 2 | B | `wave-implementer` | GLM-5.2 High | False | `wave2/agent_b_handoff.md` |
