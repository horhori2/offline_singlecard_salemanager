"""
네이버 온라인 주문 변경분 수집 + 재고 검증 서비스
"""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.product import Product, OnlineOrderLog
from app.services.naver_client import naver_client

logger = logging.getLogger(__name__)

_last_changed_from: str | None = None

INCREASE_STATUSES = {
    "PAYED",
    "PAY_DONE",
    "PRODUCT_PREPARE",
}

DECREASE_STATUSES = {
    "DELIVERED",
    "PURCHASE_DECIDED",
    "CANCELED",
    "RETURNED",
    "EXCHANGED",
}


def _utc_ago_iso(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _to_utc_iso(date_str: str) -> str:
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except Exception:
        return date_str


# ── 주문 폴링 (2분마다) ────────────────────────────────────────────────────────

async def poll_order_changes() -> None:
    global _last_changed_from

    if not _last_changed_from:
        _last_changed_from = _utc_ago_iso(60 * 24)

    try:
        changed = await naver_client.get_recent_orders(_last_changed_from)
        data = changed.get("data", changed)
        statuses = data.get("lastChangeStatuses", [])

        if not statuses:
            logger.debug("변경된 주문 없음")
            return

        logger.info("주문 변경분 수집: %d건", len(statuses))

        # ✅ 수정 1: lastChangedDate가 None인 건 제외하고 최신 날짜 추출
        dated = [s for s in statuses if s.get("lastChangedDate")]
        if dated:
            last_date = max(dated, key=lambda s: s["lastChangedDate"])["lastChangedDate"]
            _last_changed_from = _to_utc_iso(last_date)
        # lastChangedDate가 하나도 없으면 현재 시각으로 전진 (무한 루프 방지)
        else:
            _last_changed_from = _utc_ago_iso(0)

        # ✅ 수정 2: productOrderStatus → lastChangedType
        target_ids = [
            s["productOrderId"] for s in statuses
            if s.get("lastChangedType") in (INCREASE_STATUSES | DECREASE_STATUSES)
        ]

        if not target_ids:
            logger.debug("처리할 주문 없음 (상태 필터)")
            return

        # 이하 동일...

        # 50개씩 나눠서 상세 조회 (API 제한)
        saved = 0
        for i in range(0, len(target_ids), 50):
            chunk = target_ids[i:i+50]
            details = await naver_client.get_product_order_details(chunk)
            orders = details.get("data", [])

            async with AsyncSessionLocal() as db:
                for order in orders:
                    result = await _process_order(db, order)
                    if result:
                        saved += 1

        logger.info("주문 폴링 완료: 신규 저장 %d건 / 조회 %d건", saved, len(target_ids))

        # more 있으면 연속 폴링
        more = data.get("more")
        if more and more.get("moreFrom"):
            _last_changed_from = _to_utc_iso(more["moreFrom"])

    except Exception as e:
        logger.error("주문 폴링 실패: %s", e)


async def _process_order(db: AsyncSession, order: dict) -> bool:
    """
    단일 주문 처리
    - 추가구성상품도 로그에 저장 (재고 차감만 제외)
    - orderId(주문 묶음)와 productOrderId(상품별) 구분
    - 반환값: True=신규저장, False=스킵
    """
    product_order = order.get("productOrder", {})
    product_order_id = product_order.get("productOrderId", "")
    if not product_order_id:
        return False

    status = product_order.get("productOrderStatus", "")
    product_class = product_order.get("productClass", "")
    quantity = product_order.get("quantity", 1)
    product_name = product_order.get("productName", "")
    order_id = order.get("order", {}).get("orderId", "")
    seller_code = product_order.get("sellerProductCode") or product_order.get("sellerManagementCode", "")
    unit_price = product_order.get("unitPrice", 0) or 0
    delivery_method = order.get("delivery", {}).get("deliveryMethod", "") or product_order.get("expectedDeliveryMethod", "")

    # 중복 처리 방지
    existing_result = await db.execute(
        select(OnlineOrderLog).where(OnlineOrderLog.product_order_id == product_order_id)
    )
    existing_log = existing_result.scalar_one_or_none()

    # 바코드로 DB 상품 조회 (추가구성상품은 재고 차감 안 함)
    product: Product | None = None
    is_addon = (product_class == "추가구성상품")

    if seller_code and not is_addon:
        result = await db.execute(
            select(Product).where(Product.barcode == seller_code)
        )
        product = result.scalar_one_or_none()

    # ── 증가 처리 ──────────────────────────────────────────────────────────────
    if status in INCREASE_STATUSES:
        if existing_log:
            return False

        order_log = OnlineOrderLog(
            product_id=product.id if product else None,
            order_id=order_id,
            product_order_id=product_order_id,
            order_status=status,
            quantity=quantity,
            product_name=product_name,
            product_class=product_class,
            unit_price=unit_price,
            delivery_method=delivery_method,
            is_processed=False,
        )
        db.add(order_log)

        if product and not is_addon:
            product.pending_online_orders += quantity
            product.naver_stock = max(0, product.naver_stock - quantity)
            product.updated_at = datetime.utcnow()
            logger.warning(
                "🛒 온라인 주문 감지: [%s] %s — %d개 (naver_stock: %d, 대기: %d)",
                seller_code, product_name, quantity,
                product.naver_stock, product.pending_online_orders,
            )
        elif is_addon:
            logger.info("🛒 추가구성상품: %s — %d개 (재고 차감 제외)", product_name, quantity)
        else:
            logger.info("🛒 주문 감지 (DB 미등록): %s — %s", product_name, seller_code)

        await db.commit()
        return True

    # ── 감소 처리 ──────────────────────────────────────────────────────────────
    elif status in DECREASE_STATUSES:
        if not existing_log or existing_log.is_processed:
            return False

        existing_log.is_processed = True
        existing_log.order_status = status

        if product and not is_addon:
            product.pending_online_orders = max(0, product.pending_online_orders - quantity)
            product.updated_at = datetime.utcnow()

            if status in {"CANCELED", "RETURNED", "EXCHANGED"}:
                product.naver_stock += quantity

            logger.info(
                "✅ 주문 처리 완료 [%s]: %s — 상태: %s, 대기: %d개",
                seller_code, product_name, status, product.pending_online_orders,
            )

        await db.commit()
        return True

    return False


# ── 재고 검증 (30분마다) ───────────────────────────────────────────────────────

async def verify_naver_stock() -> None:
    logger.info("네이버 재고 검증 시작...")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Product))
        products = list(result.scalars().all())

    corrected = 0
    for product in products:
        if not product.naver_origin_id:
            continue
        try:
            data = await naver_client.get_product(product.naver_origin_id)
            actual_stock = data.get("originProduct", {}).get("stockQuantity")
            if actual_stock is None:
                continue

            actual_price = data.get("originProduct", {}).get("salePrice", 0)
            stock_changed = product.naver_stock != actual_stock
            price_changed = actual_price and product.naver_sale_price != actual_price

            if stock_changed or price_changed:
                if stock_changed:
                    logger.warning("📊 재고 불일치 보정: [%s] DB=%d → 실제=%d", product.name, product.naver_stock, actual_stock)
                if price_changed:
                    logger.info("💰 가격 동기화: [%s] DB=₩%d → 실제=₩%d", product.name, product.naver_sale_price, actual_price)
                async with AsyncSessionLocal() as db2:
                    p = await db2.get(Product, product.id)
                    if p:
                        if stock_changed:
                            p.naver_stock = actual_stock
                        if price_changed:
                            p.naver_sale_price = actual_price
                            p.offline_price = actual_price
                        p.updated_at = datetime.utcnow()
                        await db2.commit()
                corrected += 1
        except Exception as e:
            logger.error("재고 검증 실패 [%s]: %s", product.name, e)

    logger.info("재고 검증 완료: %d개 보정", corrected)


# ── 바코드 스캔 경고 ──────────────────────────────────────────────────────────

async def confirm_offline_sale(db: AsyncSession, product: Product, quantity: int = 1) -> str | None:
    if product.pending_online_orders > 0:
        return (
            f"⚠️ 온라인 주문된 상품입니다! "
            f"(대기 중인 온라인 주문: {product.pending_online_orders}개) "
            f"온라인 주문 처리 후 재고를 확인하세요."
        )
    return None