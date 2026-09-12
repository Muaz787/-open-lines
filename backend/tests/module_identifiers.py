"""What names a module's CODE actually references.

Parsed, not grepped. Several gates assert that a module cannot reach a dangerous
function -- prepare_profile from the collection router, submit_profile from the
reconciliation sweep -- and a substring search cannot tell a call from the prose
explaining why the call is absent, or from a constant like ADVANCED that merely
shares letters with advance(). Both of those produced false failures before this
existed, and the obvious "fix" for a false failure is to delete the explanation.

Attribute access counts: the risk is `engine.prepare_profile(...)`, which parses
as an Attribute rather than a Name.
"""
from __future__ import annotations

import ast
import inspect


def identifiers(module) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names
