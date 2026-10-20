"""The deterministic core: state, events and the reducer that applies them.

Nothing in this package performs I/O, reads the clock or calls a model
(ADR-0006). The shell around it persists state and carries out the outbox.
"""
