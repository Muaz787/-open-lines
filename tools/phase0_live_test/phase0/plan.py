"""
Operation plan + mutation gate.

Every provider operation is expressed as a PlannedOperation. In the default and
--dry-run modes NOTHING is executed. Only an explicit apply=True path may perform
a mutation, and only after the production guard has cleared every target.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .safety import Guard, SafetyError


@dataclass
class PlannedOperation:
    provider: str                 # "twilio" | "vapi" | "local"
    action: str                   # human-readable verb, e.g. "purchase_number"
    method: str                   # HTTP method or "LOCAL"
    target: str                   # resource id or "(new)"
    mutating: bool                # True if it changes external state
    detail: str = ""              # sanitized description (no secrets/numbers)
    _run: Callable[[], dict] | None = field(default=None, repr=False)

    def describe(self) -> str:
        kind = "MUTATE" if self.mutating else "read"
        return f"[{self.provider}:{kind}] {self.action} -> {self.target} ({self.method}) {self.detail}".strip()


@dataclass
class OperationPlan:
    operations: list[PlannedOperation] = field(default_factory=list)

    def add(self, op: PlannedOperation) -> None:
        self.operations.append(op)

    def render(self) -> str:
        lines = ["OPERATION PLAN (no changes made):"]
        for i, op in enumerate(self.operations, 1):
            lines.append(f"  {i}. {op.describe()}")
        muts = sum(1 for o in self.operations if o.mutating)
        lines.append(f"  — {muts} mutating operation(s), {len(self.operations) - muts} read.")
        return "\n".join(lines)

    def guard(self, guard: Guard, *, allow_create: bool = False) -> None:
        """Verify every mutating target is permitted. Creation ops target '(new)'
        and are allowed only when allow_create=True (the provision command)."""
        for op in self.operations:
            if not op.mutating:
                continue
            if op.target == "(new)":
                if not allow_create:
                    raise SafetyError(f"unexpected creation op outside provisioning: {op.action}")
                continue
            guard.assert_target_allowed(op.target)

    def execute(self, *, apply: bool) -> list[dict]:
        """Run the plan. With apply=False (default/dry-run) NO mutating op runs;
        read ops also do not touch the network here (callers gate reads too).
        Returns a list of per-op result dicts."""
        results: list[dict] = []
        for op in self.operations:
            if not apply and op.mutating:
                results.append({"action": op.action, "status": "skipped_dry_run", "mutating": True})
                continue
            if op._run is None:
                results.append({"action": op.action, "status": "no_executor"})
                continue
            if not apply:
                # Even non-mutating executors are not invoked without apply, so a
                # dry run makes zero network calls.
                results.append({"action": op.action, "status": "skipped_dry_run", "mutating": False})
                continue
            try:
                res = op._run()
                results.append({"action": op.action, "status": "ok", "result": res})
            except Exception as e:  # partial-failure recovery: stop, report progress
                results.append({"action": op.action, "status": "error", "error": type(e).__name__})
                results.append({"_partial_failure": True, "completed": len(results) - 1})
                break
        return results
