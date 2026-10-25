"""Two verified local bases, not a model catalogue or an adapter compatibility guess."""

ORIGINAL_ID = "Qwen/Qwen3.5-0.8B"
ORIGINAL_REVISION = "2fc06364715b967f1860aea9cf38778875588b17"
CAPABLE_ID = "Qwen/Qwen3.5-4B"
CAPABLE_REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
BASES = {ORIGINAL_REVISION: ORIGINAL_ID, CAPABLE_REVISION: CAPABLE_ID}


def model_limit(revision):
    if revision not in BASES:
        raise ValueError("Unsupported model revision")
    return 6_000_000_000 if revision == CAPABLE_REVISION else 3_000_000_000
