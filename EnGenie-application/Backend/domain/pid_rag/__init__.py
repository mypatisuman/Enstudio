"""Retrieval-augmented answers about a built P&ID (greenfield or brownfield).

    snapshot   one canonical view of a drawing, read from the describe store
               (SQLite studio.db) or from a solution-session PIDGraph (Mongo)
    cards      the drawing as knowledge cards: drawing, subsystem, equipment,
               instrument, loop, process run, design rationale, review notes
    index      the cards embedded with the hosted embedding model, stored next
               to the graph, re-embedded only when a card's text changed
    retriever  hybrid retrieval (exact tags + vectors + keywords) with a
               one-hop graph expansion, path tracing and element counts
    citations  checks the tags an answer cites against the drawing

LLM-only: no local model runs; embeddings are hosted (common/ai/embedding_manager).
"""
