"""
File: app/workflow_endpoints.py
Responsibility: Provide REST API endpoints for retrieving and displaying workflow logs
from Supabase. These endpoints are used by Render's log viewer to show trade analysis,
decisions, and results in a structured format.

Usage:
    from app.workflow_endpoints import setup_workflow_endpoints
    
    app = FastAPI()
    setup_workflow_endpoints(app, supabase_client)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel
from contracts.decision import Decision
from contracts.trade import Trade
from storage.supabase import SupabaseClient # Import SupabaseClient

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


# ============================================================================
# Response Models
# ============================================================================
class WorkflowEventResponse(BaseModel):
    """Response model for a single workflow event."""
    
    timestamp: datetime
    event_type: str
    symbol: str
    details: dict[str, Any]
    execution_time_ms: Optional[float] = None


class DecisionSummaryResponse(BaseModel):
    """Response model for decision summary."""
    
    symbol: str
    total_decisions: int
    approved_decisions: int
    rejected_decisions: int
    approval_rate: float
    top_rejection_reasons: dict[str, int]


class TradeSummaryResponse(BaseModel):
    """Response model for trade summary."""
    
    symbol: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float


class WorkflowStatusResponse(BaseModel):
    """Response model for overall workflow status."""
    
    symbol: str
    last_analysis_time: Optional[datetime]
    last_decision_time: Optional[datetime]
    last_trade_time: Optional[datetime]
    engine_running: bool
    recent_events: list[WorkflowEventResponse]


# ============================================================================
# Endpoints
# ============================================================================
@router.get("/status/{symbol}", response_model=WorkflowStatusResponse)
async def get_workflow_status(
    symbol: str,
    supabase_client: Any = None,
) -> WorkflowStatusResponse:
    """Get the current workflow status for a symbol.
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT").
        supabase_client: Injected Supabase client.
    
    Returns:
        WorkflowStatusResponse with recent events and status.
    """
    if supabase_client is None:
        return WorkflowStatusResponse(
            symbol=symbol,
            last_analysis_time=None,
            last_decision_time=None,
            last_trade_time=None,
            engine_running=False,
            recent_events=[],
        )
    
    # Fetch recent decisions from Supabase
    try:
        decisions = await supabase_client.fetch_decisions_by_symbol(
            symbol=symbol,
            limit=10,
        )
    except Exception:
        decisions = []
    
    # Fetch recent trades from Supabase
    try:
        trades = await supabase_client.fetch_trades_by_symbol(
            symbol=symbol,
            limit=10,
        )
    except Exception:
        trades = []
    
    # Build recent events list
    recent_events: list[WorkflowEventResponse] = []
    
    for decision_data in decisions:
        decision = Decision(**decision_data)
        event_type = "decision_approved" if decision.final_verdict else "decision_rejected"
        recent_events.append(
            WorkflowEventResponse(
                timestamp=decision.created_at,
                event_type=event_type,
                symbol=symbol,
                details={
                    "score": decision.score,
                    "confidence": decision.confidence,
                    "rejection_reason": decision.rejection_reason,
                    "entry_payload": decision.entry_payload,
                },
            )
        )
    
    for trade_data in trades:
        trade = Trade(**trade_data)
        event_type = "trade_opened" if trade.status == "open" else "trade_closed"
        recent_events.append(
            WorkflowEventResponse(
                timestamp=trade.opened_at,
                event_type=event_type,
                symbol=symbol,
                details={
                    "trade_id": str(trade.id),
                    "direction": trade.direction,
                    "entry_price": trade.entry_price,
                    "pnl": trade.pnl,
                    "close_reason": trade.close_reason,
                },
            )
        )
    
    # Sort by timestamp descending
    recent_events.sort(key=lambda x: x.timestamp, reverse=True)
    
    # Get last times
    last_analysis_time = decisions[0]["created_at"] if decisions else None
    last_decision_time = decisions[0]["created_at"] if decisions else None
    last_trade_time = trades[0]["opened_at"] if trades else None
    
    return WorkflowStatusResponse(
        symbol=symbol,
        last_analysis_time=last_analysis_time,
        last_decision_time=last_decision_time,
        last_trade_time=last_trade_time,
        engine_running=True,  # TODO: Get from Redis
        recent_events=recent_events[:20],  # Return last 20 events
    )


@router.get("/decisions/{symbol}", response_model=DecisionSummaryResponse)
async def get_decision_summary(
    symbol: str,
    hours: int = Query(24, ge=1, le=720),
    supabase_client: Any = None,
) -> DecisionSummaryResponse:
    """Get decision summary for a symbol over the past N hours.
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT").
        hours: Number of hours to look back (default: 24, max: 720).
        supabase_client: Injected Supabase client.
    
    Returns:
        DecisionSummaryResponse with decision statistics.
    """
    if supabase_client is None:
        return DecisionSummaryResponse(
            symbol=symbol,
            total_decisions=0,
            approved_decisions=0,
            rejected_decisions=0,
            approval_rate=0.0,
            top_rejection_reasons={},
        )
    
    try:
        decisions = await supabase_client.fetch_decisions_by_symbol(
            symbol=symbol,
            limit=1000,
        )
    except Exception:
        decisions = []
    
    # Filter by time
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
    decisions = [
        d for d in decisions
        if d["created_at"] >= cutoff_time
    ]
    
    total = len(decisions)
    approved = sum(1 for d in decisions if d["final_verdict"])
    rejected = total - approved
    
    # Count rejection reasons
    rejection_reasons: dict[str, int] = {}
    for d in decisions:
        if not d["final_verdict"]:
            reason = d["rejection_reason"] or "unknown"
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
    
    approval_rate = (approved / total * 100) if total > 0 else 0.0
    
    return DecisionSummaryResponse(
        symbol=symbol,
        total_decisions=total,
        approved_decisions=approved,
        rejected_decisions=rejected,
        approval_rate=round(approval_rate, 2),
        top_rejection_reasons=dict(sorted(
            rejection_reasons.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:5]),
    )


@router.get("/trades/{symbol}", response_model=TradeSummaryResponse)
async def get_trade_summary(
    symbol: str,
    hours: int = Query(24, ge=1, le=720),
    supabase_client: Any = None,
) -> TradeSummaryResponse:
    """Get trade summary for a symbol over the past N hours.
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT").
        hours: Number of hours to look back (default: 24, max: 720).
        supabase_client: Injected Supabase client.
    
    Returns:
        TradeSummaryResponse with trade statistics.
    """
    if supabase_client is None:
        return TradeSummaryResponse(
            symbol=symbol,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            total_pnl=0.0,
        )
    
    try:
        trades = await supabase_client.fetch_trades_by_symbol(
            symbol=symbol,
            limit=1000,
        )
    except Exception:
        trades = []
    
    # Filter by time and closed trades only
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
    trades = [
        t for t in trades
        if t["status"] == "closed"
        and t["closed_at"] >= cutoff_time
    ]
    
    total = len(trades)
    winning = sum(1 for t in trades if t["pnl"] > 0)
    losing = total - winning
    total_pnl = sum(t["pnl"] for t in trades)
    
    win_rate = (winning / total * 100) if total > 0 else 0.0
    
    return TradeSummaryResponse(
        symbol=symbol,
        total_trades=total,
        winning_trades=winning,
        losing_trades=losing,
        win_rate=round(win_rate, 2),
        total_pnl=round(total_pnl, 2),
    )


def setup_workflow_endpoints(app: Any, supabase_client: Any = None) -> None:
    """Setup workflow endpoints on a FastAPI app.
    
    Args:
        app: FastAPI application instance.
        supabase_client: Supabase client for database access.
    """
    app.include_router(router)
