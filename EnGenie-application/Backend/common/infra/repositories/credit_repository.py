"""
Credit repository — MongoDB persistence for the per-user credits system.

Three collections:
  user_credits          — one document per user: current balance + lifetime totals
  credit_transactions   — append-only ledger (charges, grants, top-ups, adjustments)
  credit_workflow_runs  — one document per dispatched workflow run (stream_id keyed).
                          Registered as "pending" at dispatch, atomically claimed on
                          settlement so a run is never charged twice, regardless of
                          whether the terminal event arrives from the in-process
                          worker closure or the /api/callbacks/{stream_id} endpoint.

All methods swallow and log errors — credit bookkeeping must never break a
workflow run or an API request.
"""
import logging
from datetime import datetime, timezone

from pymongo import ReturnDocument

from common.infra.mongodb_config import mongodb_manager, Collections

logger = logging.getLogger(__name__)

# Run settlement statuses
RUN_PENDING = "pending"    # dispatched, outcome unknown yet
RUN_CHARGED = "charged"    # finished successfully, credits deducted
RUN_FAILED = "failed"      # finished unsuccessfully, NOT charged
RUN_FREE = "free"          # finished successfully but cost was 0 at dispatch time


def _now():
    return datetime.now(timezone.utc)


class CreditRepository:
    def __init__(self):
        self.mongo_manager = mongodb_manager

    def _accounts(self):
        return self.mongo_manager.get_collection(Collections.USER_CREDITS)

    def _transactions(self):
        return self.mongo_manager.get_collection(Collections.CREDIT_TRANSACTIONS)

    def _runs(self):
        return self.mongo_manager.get_collection(Collections.CREDIT_WORKFLOW_RUNS)

    # ── Accounts ──────────────────────────────────────────────────────────

    def ensure_account(self, user_id: str, initial_balance: int = 0):
        """
        Return the user's credit account, creating it (with the initial grant)
        on first touch. The initial grant is recorded in the ledger.
        """
        try:
            now = _now()
            before = self._accounts().find_one_and_update(
                {"user_id": user_id},
                {
                    "$setOnInsert": {
                        "user_id": user_id,
                        "balance": initial_balance,
                        "total_granted": initial_balance,
                        "total_consumed": 0,
                        "created_at": now,
                        "updated_at": now,
                    }
                },
                upsert=True,
                return_document=ReturnDocument.BEFORE,
            )
            if before is None:
                # First touch — account was just created by this call
                if initial_balance > 0:
                    self._insert_transaction(
                        user_id=user_id,
                        txn_type="grant",
                        delta=initial_balance,
                        balance_after=initial_balance,
                        description="Initial credit grant",
                    )
                return self._accounts().find_one({"user_id": user_id})
            return before
        except Exception as e:
            logger.error(f"[CREDITS] ensure_account failed for user {user_id}: {e}")
            return None

    def get_account(self, user_id: str):
        try:
            return self._accounts().find_one({"user_id": user_id})
        except Exception as e:
            logger.error(f"[CREDITS] get_account failed for user {user_id}: {e}")
            return None

    def list_accounts(self, limit: int = 100, skip: int = 0):
        try:
            cursor = (
                self._accounts()
                .find({}, {"_id": 0})
                .sort("updated_at", -1)
                .skip(skip)
                .limit(limit)
            )
            return list(cursor)
        except Exception as e:
            logger.error(f"[CREDITS] list_accounts failed: {e}")
            return []

    def apply_delta(
        self,
        user_id: str,
        delta: int,
        txn_type: str,
        description: str = "",
        workflow_type: str = None,
        stream_id: str = None,
        session_id: str = None,
        performed_by: str = None,
        initial_balance: int = 0,
    ):
        """
        Atomically apply a signed credit delta to the user's balance and append
        a ledger entry. Returns the new balance, or None on failure.
        """
        try:
            inc = {"balance": delta}
            if delta < 0:
                inc["total_consumed"] = -delta
            else:
                inc["total_granted"] = delta

            account = self._accounts().find_one_and_update(
                {"user_id": user_id},
                {"$inc": inc, "$set": {"updated_at": _now()}},
                return_document=ReturnDocument.AFTER,
            )
            if account is None:
                # Account did not exist yet — create it, then retry once.
                self.ensure_account(user_id, initial_balance)
                account = self._accounts().find_one_and_update(
                    {"user_id": user_id},
                    {"$inc": inc, "$set": {"updated_at": _now()}},
                    return_document=ReturnDocument.AFTER,
                )
            if account is None:
                logger.error(f"[CREDITS] apply_delta could not resolve account for user {user_id}")
                return None

            self._insert_transaction(
                user_id=user_id,
                txn_type=txn_type,
                delta=delta,
                balance_after=account["balance"],
                description=description,
                workflow_type=workflow_type,
                stream_id=stream_id,
                session_id=session_id,
                performed_by=performed_by,
            )
            return account["balance"]
        except Exception as e:
            logger.error(f"[CREDITS] apply_delta failed for user {user_id} (delta={delta}): {e}")
            return None

    # ── Ledger ────────────────────────────────────────────────────────────

    def _insert_transaction(
        self,
        user_id: str,
        txn_type: str,
        delta: int,
        balance_after: int,
        description: str = "",
        workflow_type: str = None,
        stream_id: str = None,
        session_id: str = None,
        performed_by: str = None,
    ):
        try:
            self._transactions().insert_one({
                "user_id": user_id,
                "timestamp": _now(),
                "type": txn_type,           # charge | grant | topup | adjustment | refund
                "amount": abs(delta),
                "delta": delta,             # signed; negative = deduction
                "balance_after": balance_after,
                "workflow_type": workflow_type,  # solution | search | None
                "stream_id": stream_id,
                "session_id": session_id,
                "performed_by": performed_by,    # admin user_id for manual entries
                "description": description,
            })
            return True
        except Exception as e:
            logger.error(f"[CREDITS] transaction insert failed for user {user_id}: {e}")
            return False

    def get_transactions(self, user_id: str, limit: int = 50, skip: int = 0):
        try:
            cursor = (
                self._transactions()
                .find({"user_id": user_id}, {"_id": 0})
                .sort("timestamp", -1)
                .skip(skip)
                .limit(limit)
            )
            return list(cursor)
        except Exception as e:
            logger.error(f"[CREDITS] get_transactions failed for user {user_id}: {e}")
            return []

    # ── Workflow runs (pending-charge records) ────────────────────────────

    def register_run(
        self,
        stream_id: str,
        user_id: str,
        workflow_type: str,
        cost: int,
        session_id: str = None,
    ):
        """
        Record a dispatched run as pending. $setOnInsert keeps a duplicate
        dispatch of the same stream_id from resetting an already-settled run.
        """
        try:
            self._runs().update_one(
                {"stream_id": stream_id},
                {
                    "$setOnInsert": {
                        "stream_id": stream_id,
                        "user_id": user_id,
                        "workflow_type": workflow_type,
                        "cost": cost,
                        "session_id": session_id,
                        "status": RUN_PENDING,
                        "created_at": _now(),
                        "settled_at": None,
                        "settled_by": None,
                    }
                },
                upsert=True,
            )
            return True
        except Exception as e:
            logger.error(f"[CREDITS] register_run failed for stream {stream_id}: {e}")
            return False

    def claim_pending_run(self, stream_id: str, final_status: str, settled_by: str = None):
        """
        Atomically transition a run from pending to its final status.
        Returns the run document if THIS call performed the transition,
        None if the run was already settled or never registered — which is
        what makes double settlement (closure + callback) harmless.
        """
        try:
            return self._runs().find_one_and_update(
                {"stream_id": stream_id, "status": RUN_PENDING},
                {"$set": {"status": final_status, "settled_at": _now(), "settled_by": settled_by}},
                return_document=ReturnDocument.BEFORE,
            )
        except Exception as e:
            logger.error(f"[CREDITS] claim_pending_run failed for stream {stream_id}: {e}")
            return None


credit_repository = CreditRepository()
