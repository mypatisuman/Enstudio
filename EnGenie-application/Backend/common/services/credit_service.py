"""
Credit service — business rules for workflow credit tracking and enforcement.

Flat credits are charged per successful workflow run:
  solution agent → CREDITS_SOLUTION_COST (default 10)
  search agent   → CREDITS_SEARCH_COST  (default 5)

Failed runs are never charged. Enforcement is OFF by default
(CREDITS_ENFORCEMENT_ENABLED) — with it off the system is pure tracking:
runs are never blocked and balances may go negative. Flip it on to reject
runs with HTTP 402 when the balance can't cover the cost.

Lifecycle of a charge:
  1. register_workflow_run()  — at dispatch time, while user_id is in scope.
     Writes a "pending" run record keyed by stream_id with the cost snapshot.
  2. settle_workflow_run()    — at the terminal event, wherever it lands
     (in-process worker closure OR the worker-callback endpoint). Atomically
     claims the pending record, so calling it from both paths is safe; only
     the first claim charges. Unsettled runs (crash, watchdog timeout before
     any hook fires) simply never charge.

Every function here swallows its own errors — credit bookkeeping must never
take down a workflow run.
"""
import logging
import os

from common.infra.repositories.credit_repository import (
    credit_repository,
    RUN_CHARGED,
    RUN_FAILED,
    RUN_FREE,
)

logger = logging.getLogger(__name__)

# ── Configuration (env-driven, matching codebase convention) ──────────────
CREDITS_SOLUTION_COST = int(os.getenv("CREDITS_SOLUTION_COST", "10"))
CREDITS_SEARCH_COST = int(os.getenv("CREDITS_SEARCH_COST", "5"))
CREDITS_INITIAL_BALANCE = int(os.getenv("CREDITS_INITIAL_BALANCE", "100"))
CREDITS_ENFORCEMENT_ENABLED = os.getenv("CREDITS_ENFORCEMENT_ENABLED", "false").lower().strip() in ("1", "true", "yes")

WORKFLOW_COSTS = {
    "solution": CREDITS_SOLUTION_COST,
    "search": CREDITS_SEARCH_COST,
}


def get_workflow_cost(workflow_type: str) -> int:
    return WORKFLOW_COSTS.get(workflow_type, 0)


def check_workflow_allowed(user_id, workflow_type: str) -> dict:
    """
    Pre-dispatch gate. Always ensures the user's credit account exists (first
    touch grants CREDITS_INITIAL_BALANCE). Blocks only when enforcement is on
    AND the balance can't cover the workflow cost.
    """
    result = {
        "allowed": True,
        "enforcement_enabled": CREDITS_ENFORCEMENT_ENABLED,
        "cost": get_workflow_cost(workflow_type),
        "balance": None,
        "reason": None,
    }
    try:
        if not user_id:
            return result
        account = credit_repository.ensure_account(str(user_id), CREDITS_INITIAL_BALANCE)
        if account is not None:
            result["balance"] = account.get("balance")
        if not CREDITS_ENFORCEMENT_ENABLED or result["cost"] <= 0:
            return result
        if account is None:
            # Can't read the balance — fail open, tracking must not block work
            return result
        if account.get("balance", 0) < result["cost"]:
            result["allowed"] = False
            result["reason"] = (
                f"This {workflow_type} run costs {result['cost']} credits but your "
                f"balance is {account.get('balance', 0)}. Please top up to continue."
            )
        return result
    except Exception as e:
        logger.error(f"[CREDITS] check_workflow_allowed failed for user {user_id}: {e}")
        return result  # fail open


def register_workflow_run(stream_id, user_id, workflow_type: str, session_id=None) -> bool:
    """Record a dispatched run as pending-charge. No-op without user/stream ids."""
    try:
        if not stream_id or not user_id:
            return False
        cost = get_workflow_cost(workflow_type)
        credit_repository.ensure_account(str(user_id), CREDITS_INITIAL_BALANCE)
        return credit_repository.register_run(
            stream_id=str(stream_id),
            user_id=str(user_id),
            workflow_type=workflow_type,
            cost=cost,
            session_id=str(session_id) if session_id else None,
        )
    except Exception as e:
        logger.error(f"[CREDITS] register_workflow_run failed for stream {stream_id}: {e}")
        return False


def settle_workflow_run(stream_id, success: bool, source: str = "in-process"):
    """
    Settle a pending run: charge on success, mark failed otherwise.
    Idempotent — only the call that claims the pending record charges.
    Safe to call for streams that were never registered (returns None).
    """
    try:
        if not stream_id:
            return None
        if success:
            final_status = RUN_CHARGED
        else:
            final_status = RUN_FAILED
        run = credit_repository.claim_pending_run(str(stream_id), final_status, settled_by=source)
        if run is None:
            return None  # already settled, or not a credit-tracked stream

        cost = run.get("cost", 0)
        if not success:
            logger.info(f"[CREDITS] Run {stream_id} ({run.get('workflow_type')}) failed — no charge")
            return {"charged": False, "cost": cost, "status": RUN_FAILED}

        if cost <= 0:
            # Already claimed as charged above — correct the final status
            credit_repository._runs().update_one(
                {"stream_id": str(stream_id)}, {"$set": {"status": RUN_FREE}}
            )
            return {"charged": False, "cost": 0, "status": RUN_FREE}

        new_balance = credit_repository.apply_delta(
            user_id=run["user_id"],
            delta=-cost,
            txn_type="charge",
            description=f"{run.get('workflow_type', 'workflow')} agent run",
            workflow_type=run.get("workflow_type"),
            stream_id=str(stream_id),
            session_id=run.get("session_id"),
            initial_balance=CREDITS_INITIAL_BALANCE,
        )
        logger.info(
            f"[CREDITS] Charged {cost} credits to user {run['user_id']} for "
            f"{run.get('workflow_type')} run {stream_id} (balance: {new_balance})"
        )
        return {"charged": True, "cost": cost, "balance": new_balance, "status": RUN_CHARGED}
    except Exception as e:
        logger.error(f"[CREDITS] settle_workflow_run failed for stream {stream_id}: {e}")
        return None


def get_balance_summary(user_id) -> dict:
    """Balance + config snapshot for the credits UI."""
    account = credit_repository.ensure_account(str(user_id), CREDITS_INITIAL_BALANCE) or {}
    return {
        "user_id": str(user_id),
        "balance": account.get("balance", 0),
        "total_granted": account.get("total_granted", 0),
        "total_consumed": account.get("total_consumed", 0),
        "enforcement_enabled": CREDITS_ENFORCEMENT_ENABLED,
        "workflow_costs": dict(WORKFLOW_COSTS),
    }


def get_history(user_id, limit: int = 50, skip: int = 0):
    return credit_repository.get_transactions(str(user_id), limit=limit, skip=skip)


def admin_adjust(user_id, amount: int, performed_by, note: str = ""):
    """
    Manual balance change by an admin. Positive amount = top-up,
    negative = downward adjustment. Returns the new balance or None.
    """
    txn_type = "topup" if amount > 0 else "adjustment"
    credit_repository.ensure_account(str(user_id), CREDITS_INITIAL_BALANCE)
    return credit_repository.apply_delta(
        user_id=str(user_id),
        delta=amount,
        txn_type=txn_type,
        description=note or f"Manual {txn_type} by admin",
        performed_by=str(performed_by) if performed_by else None,
        initial_balance=CREDITS_INITIAL_BALANCE,
    )
