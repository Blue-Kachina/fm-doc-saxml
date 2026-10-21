"""fm-saxml: FileMaker Save As XML documentation generator.

Read converted docs with ``fm_saxml.load(docs_dir)`` or ``fm_saxml.find_docs(name)``
(see ``fm_saxml.api`` and docs/contract.md).
"""

__version__ = "0.6.2"

from .api import BatchDocs, DocsNotFoundError, ResolvedRef, SolutionDocs, find_docs, load  # noqa: E402
from .contract_migrations import ContractVersionError  # noqa: E402

__all__ = [
    "__version__",
    "load",
    "find_docs",
    "SolutionDocs",
    "BatchDocs",
    "ResolvedRef",
    "DocsNotFoundError",
    "ContractVersionError",
]
