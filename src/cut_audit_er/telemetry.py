"""Optional durable observation journal; never a selector input or final result.

A killed sequential worker may have bought one answer after its last durable
receipt. Recovery reports that uncertainty instead of calling a prefix complete.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path


SCHEMA = "cut-audit-answer-journal-v1"
MAX_JOURNAL_BYTES = 64 * 1024 * 1024


def _bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def validate_identity(identity: dict) -> None:
    if not isinstance(identity, dict):
        raise ValueError("Journal identity must be a mapping")
    if type(identity.get("requested_budget")) is not int or identity["requested_budget"] < 0:
        raise ValueError("Journal identity requires a nonnegative integer budget")
    if not isinstance(identity.get("method"), str) or not identity["method"]:
        raise ValueError("Journal identity requires a method")
    _bytes(identity)


class AuditJournal:
    """Exclusive append-only writer, flushing each receipt before proceeding."""

    def __init__(self, path: Path, identity: dict):
        validate_identity(identity)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("xb")
        self._seq = 0
        self._previous = None
        try:
            self({"kind": "header", "identity": identity})
        except BaseException:
            self.close()
            raise

    def __call__(self, event: dict) -> None:
        body = {"schema": SCHEMA, "seq": self._seq,
                "previous_sha256": self._previous, "event": event}
        digest = hashlib.sha256(_bytes(body)).hexdigest()
        line = _bytes(body | {"sha256": digest}) + b"\n"
        written = self._file.write(line)
        if written != len(line):
            raise OSError("Incomplete journal write")
        self._file.flush()
        os.fsync(self._file.fileno())
        self._seq += 1
        self._previous = digest

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _checkpoint(value: dict, spent: int, identity: dict) -> None:
    if not isinstance(value, dict) or type(value.get("spent")) is not int or value["spent"] != spent:
        raise ValueError("Journal checkpoint spend gap")
    for name in ("fp", "fn", "loss"):
        if not isinstance(value.get(name), (int, float)) or not math.isfinite(value[name]):
            raise ValueError("Journal checkpoint requires finite FP/FN/loss")
    if value["fp"] < 0 or value["fn"] < 0:
        raise ValueError("Negative journal error count")
    weight = identity.get("fn_weight", 1.)
    if not math.isclose(value["loss"], value["fp"] + weight * value["fn"], abs_tol=1e-9):
        raise ValueError("Journal checkpoint loss mismatch")


def recover_journal(path: Path, expected_identity: dict) -> dict:
    """Validate a complete prefix; reject corruption or another run's identity.

    Only a final line without its newline may be ignored. A malformed complete
    line, chain gap, duplicate purchase, or identity mismatch is never accepted.
    The returned last checkpoint is explicitly partial, never a final metric.
    """
    validate_identity(expected_identity)
    path = Path(path)
    empty = {"completed_result_available": False, "confirmed_paid_answers": None,
             "paid_count_lower_bound": None, "paid_count_upper_bound": None,
             "paid_count_exact": False, "decisions": [], "trace": [],
             "last_evaluated_checkpoint": None, "terminal_marker": None}
    if not path.exists():
        return empty | {"journal_status": "missing_journal"}
    if path.stat().st_size > MAX_JOURNAL_BYTES:
        raise ValueError("Journal byte cap exceeded")
    data = path.read_bytes()
    parts = data.splitlines(keepends=True)
    truncated = bool(parts and not parts[-1].endswith(b"\n"))
    tail_bytes = len(parts[-1]) if truncated else 0
    lines = parts[:-1] if truncated else parts
    if not lines:
        return empty | {"journal_status": "missing_valid_header", "truncated_tail_bytes": tail_bytes,
                        "journal_sha256": hashlib.sha256(data).hexdigest()}
    budget = expected_identity["requested_budget"]
    if len(lines) > 2 * budget + 3:
        raise ValueError("Journal has too many records for its budget")
    previous = None
    decisions, trace, pairs = [], [], set()
    terminal = None
    pending = False
    for sequence, line in enumerate(lines):
        try:
            record = json.loads(line)
            digest = record.pop("sha256")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError("Malformed complete journal record") from exc
        if (record.get("schema") != SCHEMA or type(record.get("seq")) is not int or record.get("seq") != sequence or
                record.get("previous_sha256") != previous or
                hashlib.sha256(_bytes(record)).hexdigest() != digest):
            raise ValueError("Journal hash/sequence chain mismatch")
        previous = digest
        event = record.get("event")
        if not isinstance(event, dict):
            raise ValueError("Malformed journal event")
        kind = event.get("kind")
        if sequence == 0:
            if kind != "header" or _bytes(event.get("identity")) != _bytes(expected_identity):
                raise ValueError("Journal identity mismatch")
            continue
        if terminal is not None:
            raise ValueError("Journal record after terminal marker")
        if kind == "initial":
            if sequence != 1:
                raise ValueError("Journal initial checkpoint missing or repeated")
            _checkpoint(event.get("checkpoint"), 0, expected_identity)
            trace.append(event["checkpoint"])
        elif kind == "answer":
            if not trace or pending:
                raise ValueError("Journal answer before initial or pending checkpoint")
            decision = event.get("decision", {})
            spent = len(decisions) + 1
            if type(decision.get("spent")) is not int or decision["spent"] != spent or spent > budget:
                raise ValueError("Journal purchase spend gap or budget excess")
            pair = decision.get("pair")
            if (not isinstance(pair, list) or len(pair) != 2 or
                    not all(isinstance(x, str) for x in pair) or pair[0] == pair[1] or
                    type(decision.get("observed_match")) is not bool):
                raise ValueError("Malformed journal purchased answer")
            key = tuple(sorted(pair))
            if key in pairs:
                raise ValueError("Repeated purchased pair in journal")
            pairs.add(key)
            decisions.append(decision)
            pending = True
        elif kind == "checkpoint":
            if not pending:
                raise ValueError("Journal checkpoint without purchased answer")
            _checkpoint(event.get("checkpoint"), len(decisions), expected_identity)
            trace.append(event["checkpoint"])
            pending = False
        elif kind == "terminal":
            if (not trace or pending or event.get("spent") != len(decisions) or
                    type(event.get("complete")) is not bool):
                raise ValueError("Invalid journal terminal marker")
            terminal = event
        else:
            raise ValueError("Unknown journal event or missing initial checkpoint")
    confirmed = len(decisions)
    exact = terminal is not None or confirmed == budget
    # A valid header without the initial checkpoint precedes every purchase.
    upper = confirmed if exact or not trace else min(budget, confirmed + 1)
    return {"journal_status": "truncated_tail" if truncated else "terminal_marker" if terminal else
            "valid_prefix" if trace else "missing_initial_checkpoint",
            "journal_sha256": hashlib.sha256(data).hexdigest(), "valid_records": len(lines),
            "last_record_sha256": previous, "truncated_tail_bytes": tail_bytes,
            "completed_result_available": False, "confirmed_paid_answers": confirmed,
            "paid_count_lower_bound": confirmed, "paid_count_upper_bound": upper,
            "paid_count_exact": exact or not trace, "decisions": decisions, "trace": trace,
            "last_evaluated_checkpoint": trace[-1] if trace else None,
            "terminal_marker": terminal,
            "scope": "Durable observed prefix only. At most one unlogged purchased answer under this sequential fail-fast callback contract; never fill forward partial performance."}
