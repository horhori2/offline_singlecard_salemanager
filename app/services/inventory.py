from __future__ import annotations
"""
재고 관리 핵심 비즈니스 로직
- 오프라인 재고 차감 (바코드 스캔)
- 네이버 스토어 재고 동기화
- 재고 부족 감지
"""
import logging
from datetime import datetime

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.product import Product, SyncLog
from app.models.schemas import (
    ProductCreate, ProductUpdate, StockAdjust,
    SyncResult, BulkSyncResult,
)
from app.services.naver_client import naver_client
from app.services.order_sync import confirm_offline_sale

logger = logging.getLogger(__name__)
settings = get_settings()


# ── 상품 CRUD ──────────────────────────────────────────────────────────────────

async def create_product(db: AsyncSession, data: ProductCreate) -> Product:
    product = Product(
        barcode=data.barcode,
        name=data.name,
        offline_stock=data.offline_stock,
        naver_stock=data.naver_stock,
        naver_channel_id=data.naver_channel_id,
        naver_origin_id=data.naver_origin_id,
        naver_option_id=data.naver_option_id,
        naver_sale_price=data.naver_sale_price,
        is_synced=True,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    await _write_log(db, product.id, "CREATE", f"상품 등록: {product.name}")
    return product


async def get_product_by_id(db: AsyncSession, product_id: int) -> Product | None:
    result = await db.execute(select(Product).where(Product.id == product_id))
    return result.scalar_one_or_none()


async def get_product_by_barcode(db: AsyncSession, barcode: str) -> Product | None:
    result = await db.execute(select(Product).where(Product.barcode == barcode))
    return result.scalar_one_or_none()


async def list_products(
    db: AsyncSession,
    search: str | None = None,
    low_stock_only: bool = False,
    unsynced_only: bool = False,
) -> list[Product]:
    stmt = select(Product)
    conditions = []
    if search:
        conditions.append(
            Product.name.contains(search) | Product.barcode.contains(search)
        )
    if low_stock_only:
        conditions.append(
            (Product.offline_stock < settings.low_stock_threshold) |
            (Product.naver_stock < settings.low_stock_threshold)
        )
    if unsynced_only:
        conditions.append(Product.is_synced == False)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    result = await db.execute(stmt.order_by(Product.id.asc()))
    return list(result.scalars().all())


async def update_product(db: AsyncSession, product_id: int, data: ProductUpdate) -> Product | None:
    product = await get_product_by_id(db, product_id)
    if not product:
        return None
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(product, field, value)
    product.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(product)
    return product


async def delete_product(db: AsyncSession, product_id: int) -> bool:
    product = await get_product_by_id(db, product_id)
    if not product:
        return False
    await db.delete(product)
    await db.commit()
    return True


# ── 재고 조정 ──────────────────────────────────────────────────────────────────

async def adjust_stock(
    db: AsyncSession,
    product_id: int,
    data: StockAdjust,
) -> tuple[Product, SyncResult | None]:
    """오프라인 또는 네이버 재고를 절대값으로 수정"""
    product = await get_product_by_id(db, product_id)
    if not product:
        raise ValueError(f"상품 ID {product_id} 없음")

    before_offline = product.offline_stock
    before_naver = product.naver_stock

    if data.offline_stock is not None:
        product.offline_stock = data.offline_stock
    if data.naver_stock is not None:
        product.naver_stock = data.naver_stock

    product.is_synced = False
    product.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(product)

    await _write_log(
        db, product.id, "STOCK_UPDATE",
        f"재고 수동 수정: 오프라인 {before_offline}→{product.offline_stock}, 네이버 {before_naver}→{product.naver_stock}",
        before_offline=before_offline, after_offline=product.offline_stock,
        before_naver=before_naver, after_naver=product.naver_stock,
    )

    sync_result = None
    if data.sync_to_naver and product.naver_origin_id:
        sync_result = await sync_product_to_naver(db, product)

    return product, sync_result


async def deduct_by_barcode(
    db: AsyncSession,
    barcode: str,
    quantity: int = 1,
    sync_to_naver: bool = True,
) -> tuple[Product, SyncResult | None, str | None]:
    """바코드 스캔 → 온라인 주문 경고 확인 → 오프라인 재고 차감 → 네이버 동기화"""
    product = await get_product_by_barcode(db, barcode)
    if not product:
        raise ValueError(f"바코드 미등록: {barcode}")
    if product.offline_stock < quantity:
        raise ValueError(
            f"재고 부족: 현재 {product.offline_stock}개, 요청 {quantity}개"
        )

    # 온라인 주문 대기 여부 확인 → 경고 메시지 생성
    warning = await confirm_offline_sale(db, product, quantity)

    before = product.offline_stock
    product.offline_stock -= quantity
    product.is_synced = False
    product.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(product)

    await _write_log(
        db, product.id, "SALE",
        f"판매 차감 -{quantity}개: {before}→{product.offline_stock}",
        before_offline=before, after_offline=product.offline_stock,
    )

    if product.offline_stock <= settings.low_stock_threshold:
        logger.warning("⚠️  재고 부족 알림: [%s] %s — 잔여 %d개", barcode, product.name, product.offline_stock)

    sync_result = None
    if sync_to_naver and product.naver_origin_id:
        sync_result = await sync_product_to_naver(db, product)

    return product, sync_result, warning


# ── 네이버 동기화 ──────────────────────────────────────────────────────────────

async def sync_product_to_naver(
    db: AsyncSession,
    product: Product,
) -> SyncResult:
    """단일 상품을 네이버 스토어에 동기화"""
    if not product.naver_origin_id:
        return SyncResult(
            product_id=product.id,
            product_name=product.name,
            success=False,
            message="원상품번호가 등록되지 않았습니다.",
        )

    target_stock = product.offline_stock
    before_naver = product.naver_stock

    try:
        if product.naver_option_id:
            await naver_client.update_stock(
                product.naver_origin_id,
                product.naver_option_id,
                target_stock,
            )
        else:
            await naver_client.update_stock_by_origin_product(
                product.naver_origin_id,
                target_stock,
            )

        product.naver_stock = target_stock
        product.is_synced = True
        product.last_synced_at = datetime.utcnow()
        product.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(product)

        await _write_log(
            db, product.id, "SYNC",
            f"네이버 동기화 완료: {before_naver}→{target_stock}",
            before_naver=before_naver, after_naver=target_stock,
            success=True,
        )
        return SyncResult(
            product_id=product.id,
            product_name=product.name,
            success=True,
            message=f"동기화 완료 (재고: {target_stock}개)",
            naver_stock_after=target_stock,
        )

    except Exception as exc:
        logger.error("네이버 동기화 실패 [%s]: %s", product.name, exc)
        await _write_log(
            db, product.id, "ERROR",
            f"네이버 동기화 실패: {exc}",
            success=False,
        )
        return SyncResult(
            product_id=product.id,
            product_name=product.name,
            success=False,
            message=str(exc),
        )


async def sync_all_unsynced(db: AsyncSession) -> BulkSyncResult:
    """미동기화 상품 전체 일괄 동기화"""
    products = await list_products(db, unsynced_only=True)
    results: list[SyncResult] = []

    for product in products:
        result = await sync_product_to_naver(db, product)
        results.append(result)

    succeeded = sum(1 for r in results if r.success)
    return BulkSyncResult(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
    )


# ── 로그 ──────────────────────────────────────────────────────────────────────

async def _write_log(
    db: AsyncSession,
    product_id: int,
    action: str,
    message: str,
    before_offline: int | None = None,
    after_offline: int | None = None,
    before_naver: int | None = None,
    after_naver: int | None = None,
    success: bool = True,
) -> None:
    log = SyncLog(
        product_id=product_id,
        action=action,
        message=message,
        before_offline=before_offline,
        after_offline=after_offline,
        before_naver=before_naver,
        after_naver=after_naver,
        success=success,
    )
    db.add(log)
    await db.commit()


async def get_logs(
    db: AsyncSession,
    product_id: int | None = None,
    limit: int = 50,
) -> list[SyncLog]:
    stmt = select(SyncLog).order_by(SyncLog.created_at.desc()).limit(limit)
    if product_id:
        stmt = stmt.where(SyncLog.product_id == product_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())
