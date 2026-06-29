from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Revenue, Sponsor
from app.schemas import RevenueSummaryResponse

router = APIRouter(prefix="/revenue", tags=["revenue"])


@router.get("/summary", response_model=RevenueSummaryResponse)
def get_revenue_summary(db: Session = Depends(get_db)):
    month_key = func.strftime("%Y-%m", Revenue.date)
    monthly_rows = (
        db.query(
            month_key.label("month"),
            func.sum(Revenue.amount).label("total"),
        )
        .group_by(month_key)
        .order_by(month_key)
        .all()
    )
    monthly_totals = [
        {"month": row.month or "", "total": float(row.total or 0)}
        for row in monthly_rows
    ]

    sponsor_rows = (
        db.query(Sponsor.name, func.sum(Revenue.amount).label("total"))
        .join(Revenue, Revenue.sponsor_id == Sponsor.id)
        .group_by(Sponsor.name)
        .all()
    )
    by_sponsor = [
        {"sponsor": row.name, "total": float(row.total or 0)}
        for row in sponsor_rows
    ]

    type_rows = (
        db.query(Revenue.type, func.sum(Revenue.amount).label("total"))
        .group_by(Revenue.type)
        .all()
    )
    by_type = [
        {"type": row.type, "total": float(row.total or 0)}
        for row in type_rows
    ]

    return RevenueSummaryResponse(
        monthly_totals=monthly_totals,
        by_sponsor=by_sponsor,
        by_type=by_type,
    )
