from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.schemas import SyncLogResponse, BulkSyncResult
from app.models.product import OnlineOrderLog, Product, SyncLog
from app.services.order_sync import poll_order_changes, _utc_ago_iso
from app.services import inventory as svc
from app.services.naver_client import naver_client
from sqlalchemy import select, desc

router = APIRouter(tags=["시스템 & 동기화"])


@router.get("/health", summary="서버 및 네이버 API 연결 상태")
async def health():
    naver_ok = await naver_client.health_check()
    return {
        "server": "ok",
        "naver_api": "connected" if naver_ok else "disconnected",
    }


@router.post("/sync/all", response_model=BulkSyncResult, summary="전체 미동기화 상품 일괄 동기화")
async def bulk_sync(db: AsyncSession = Depends(get_db)):
    return await svc.sync_all_unsynced(db)


@router.get("/logs", summary="전체 동기화 로그")
async def all_logs(
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(SyncLog, Product.name, Product.barcode)
        .outerjoin(Product, SyncLog.product_id == Product.id)
        .order_by(desc(SyncLog.created_at))
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            "id": log.id,
            "product_id": log.product_id,
            "product_name": name or "",
            "product_barcode": barcode or "",
            "action": log.action,
            "message": log.message,
            "before_offline": log.before_offline,
            "after_offline": log.after_offline,
            "before_naver": log.before_naver,
            "after_naver": log.after_naver,
            "success": log.success,
            "created_at": log.created_at,
        }
        for log, name, barcode in rows
    ]


@router.get("/online-orders", summary="온라인 주문 목록 조회")
async def get_online_orders(
    limit: int = Query(200, le=1000),
    unprocessed_only: bool = Query(False, description="미처리 주문만"),
    registered_only: bool = Query(False, description="DB 등록 상품 주문만"),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(OnlineOrderLog).order_by(desc(OnlineOrderLog.created_at)).limit(limit)
    if unprocessed_only:
        stmt = stmt.where(OnlineOrderLog.is_processed == False)
    if registered_only:
        stmt = stmt.where(OnlineOrderLog.product_id != None)
    result = await db.execute(stmt)
    logs = result.scalars().all()
    return [
        {
            "id": l.id,
            "product_id": l.product_id,
            "order_id": l.order_id,
            "product_order_id": l.product_order_id,
            "product_name": l.product_name,
            "product_class": l.product_class,
            "unit_price": l.unit_price,
            "delivery_method": l.delivery_method,
            "order_status": l.order_status,
            "quantity": l.quantity,
            "is_processed": l.is_processed,
            "created_at": l.created_at,
        }
        for l in logs
    ]


from app.models.product import OfflineOrder, OfflineOrderItem


@router.post("/online-orders/force-collect", summary="오늘 결제 주문 강제 재수집")
async def force_collect_today_orders():
    """
    lastChangedDate가 없어 폴링에서 누락된 주문 보완
    오늘 00:00부터 현재까지 결제된 PAYED/PRODUCT_PREPARE 주문을 강제 수집
    """
    from app.services import order_sync
    from datetime import datetime, timezone
    import asyncio

    # 오늘 KST 00:00을 UTC로 변환
    today_kst = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    from_date = today_kst.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    try:
        result = await naver_client.get_payed_orders_by_date(from_date)
        data = result.get("data", {})
        statuses = data.get("lastChangeStatuses", [])

        if not statuses:
            return {"collected": 0, "message": "새로운 주문 없음"}

        target_ids = [s["productOrderId"] for s in statuses]
        details = await naver_client.get_product_order_details(target_ids)
        orders = details.get("data", [])

        from app.core.database import AsyncSessionLocal
        saved = 0
        for i in range(0, len(orders), 50):
            chunk = orders[i:i+50]
            async with AsyncSessionLocal() as db:
                for order in chunk:
                    r = await order_sync._process_order(db, order)
                    if r:
                        saved += 1

        return {"collected": len(statuses), "saved": saved, "message": f"{saved}건 신규 저장"}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(500, str(e))

@router.post("/offline-orders", summary="오프라인 주문 저장")
async def create_offline_order(data: dict, db: AsyncSession = Depends(get_db)):
    """POS 결제 완료 시 주문 저장"""
    items = data.get("items", [])
    if not items:
        from fastapi import HTTPException
        raise HTTPException(400, "상품이 없습니다")

    total_amount = sum(i.get("unit_price", 0) * i.get("quantity", 1) for i in items)
    total_qty = sum(i.get("quantity", 1) for i in items)

    order = OfflineOrder(total_amount=total_amount, total_qty=total_qty)
    db.add(order)
    await db.flush()

    for item in items:
        db.add(OfflineOrderItem(
            order_id=order.id,
            product_id=item.get("product_id"),
            product_name=item.get("name", ""),
            barcode=item.get("barcode", ""),
            quantity=item.get("quantity", 1),
            unit_price=item.get("unit_price", 0),
            subtotal=item.get("unit_price", 0) * item.get("quantity", 1),
        ))

    await db.commit()
    return {"id": order.id, "total_amount": total_amount, "total_qty": total_qty}


@router.get("/offline-orders", summary="오프라인 주문 목록 조회")
async def get_offline_orders(
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(OfflineOrder).order_by(desc(OfflineOrder.created_at)).limit(limit)
    result = await db.execute(stmt)
    orders = result.scalars().all()

    out = []
    for o in orders:
        items_stmt = select(OfflineOrderItem).where(OfflineOrderItem.order_id == o.id)
        items_result = await db.execute(items_stmt)
        items = items_result.scalars().all()
        out.append({
            "id": o.id,
            "total_amount": o.total_amount,
            "total_qty": o.total_qty,
            "created_at": o.created_at,
            "items": [
                {
                    "product_name": i.product_name,
                    "barcode": i.barcode,
                    "quantity": i.quantity,
                    "unit_price": i.unit_price,
                    "subtotal": i.subtotal,
                }
                for i in items
            ]
        })
    return out

@router.post("/online-orders/{order_log_id}/confirm", summary="온라인 주문 확인 (오프라인 재고 차감)")
async def confirm_online_order(
    order_log_id: int,
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException
    from datetime import datetime

    log_result = await db.execute(
        select(OnlineOrderLog).where(OnlineOrderLog.id == order_log_id)
    )
    order_log = log_result.scalar_one_or_none()

    if not order_log:
        raise HTTPException(404, "주문을 찾을 수 없습니다")
    if order_log.is_processed:
        raise HTTPException(400, "이미 처리된 주문입니다")

    if order_log.product_id:
        product_result = await db.execute(
            select(Product).where(Product.id == order_log.product_id)
        )
        product = product_result.scalar_one_or_none()
        if product:
            product.offline_stock = max(0, product.offline_stock - order_log.quantity)
            product.pending_online_orders = max(0, product.pending_online_orders - order_log.quantity)
            product.updated_at = datetime.utcnow()

    order_log.is_processed = True
    await db.commit()

    return {
        "success": True,
        "order_log_id": order_log_id,
        "quantity": order_log.quantity,
        "message": f"오프라인 재고 {order_log.quantity}개 차감 완료",
    }