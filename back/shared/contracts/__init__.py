"""Shared contract modules.

Import contracts from their owning module (for example
``back.shared.contracts.agent``).  Keeping the package initializer free of eager
re-exports prevents low-level contracts such as ``common`` from importing the
entire Agent/application graph during Python package initialization.
"""

__all__: list[str] = []
