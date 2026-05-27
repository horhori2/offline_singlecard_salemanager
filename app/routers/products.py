from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.schemas import (
    ProductCreate, ProductUpdate, ProductResponse,
    StockAdjust, BarcodeStockUpdate,
    SyncResult, BulkSyncResult, SyncLogResponse,
)
from app.services import inventory as svc
from app.services.excel_import import import_from_excel
from app.models.schemas import ExcelImportResult
from fastapi import UploadFile, File

router = APIRouter(tags=["상품 & 재고"])


@router.get("", response_model=list[ProductResponse], summary="상품 목록 조회")
async def list_products(
    search: str | None = Query(None, description="상품명 또는 바코드 검색"),
    low_stock: bool = Query(False, description="재고 부족 상품만"),
    unsynced: bool = Query(False, description="미동기화 상품만"),
    db: AsyncSession = Depends(get_db),
):
    return await svc.list_products(db, search=search, low_stock_only=low_stock, unsynced_only=unsynced)


@router.post("", response_model=ProductResponse, status_code=201, summary="상품 등록")
async def create_product(data: ProductCreate, db: AsyncSession = Depends(get_db)):
    return await svc.create_product(db, data)


@router.get("/naver/{naver_product_id}", summary="네이버 상품번호로 스마트스토어 상품 조회")
async def get_naver_product(naver_product_id: str):
    """
    원상품(originProductNo) 또는 채널상품(channelProductNo) 번호로 조회.
    v2 원상품 → v2 채널상품 → v1 원상품 순으로 시도합니다.
    """
    import httpx
    from app.services.naver_client import naver_client
    errors = {}

    # 1) v2 원상품 조회
    try:
        return await naver_client.get_product(naver_product_id)
    except Exception as e:
        errors["v2_origin"] = str(e)

    # 2) v2 채널상품 조회
    try:
        return await naver_client.get_channel_product(naver_product_id)
    except Exception as e:
        errors["v2_channel"] = str(e)

    # 3) v1 원상품 조회 (구버전 fallback)
    try:
        headers = await naver_client._headers()
        async with httpx.AsyncClient() as c:
            resp = await c.get(
                f"{naver_client.base_url}/v1/products/{naver_product_id}",
                headers=headers, timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        errors["v1_origin"] = str(e)

    raise HTTPException(404, {"message": "모든 경로에서 상품을 찾을 수 없습니다.", "errors": errors})


@router.get("/{product_id}", response_model=ProductResponse, summary="상품 단건 조회")
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)):
    product = await svc.get_product_by_id(db, product_id)
    if not product:
        raise HTTPException(404, "상품을 찾을 수 없습니다.")
    return product


@router.patch("/{product_id}", response_model=ProductResponse, summary="상품 정보 수정")
async def update_product(product_id: int, data: ProductUpdate, db: AsyncSession = Depends(get_db)):
    product = await svc.update_product(db, product_id, data)
    if not product:
        raise HTTPException(404, "상품을 찾을 수 없습니다.")
    return product


@router.delete("/{product_id}", status_code=204, summary="상품 삭제")
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db)):
    ok = await svc.delete_product(db, product_id)
    if not ok:
        raise HTTPException(404, "상품을 찾을 수 없습니다.")


# ── 재고 조정 ────────────────────────────────────────────────────────────────

@router.put("/{product_id}/stock", response_model=ProductResponse, summary="재고 수동 수정")
async def adjust_stock(
    product_id: int,
    data: StockAdjust,
    db: AsyncSession = Depends(get_db),
):
    try:
        product, _ = await svc.adjust_stock(db, product_id, data)
        return product
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/barcode/deduct", summary="바코드 스캔 재고 차감")
async def deduct_by_barcode(data: BarcodeStockUpdate, db: AsyncSession = Depends(get_db)):
    """
    오프라인 바코드 스캐너로 판매 시 호출.
    재고 1개 차감 후 네이버 스토어 즉시 동기화.
    온라인 주문 대기 중이면 warning 필드에 경고 메시지 포함.
    """
    try:
        product, _, warning = await svc.deduct_by_barcode(
            db, data.barcode, data.quantity, data.sync_to_naver
        )
        result = {
            "id": product.id,
            "barcode": product.barcode,
            "name": product.name,
            "offline_stock": product.offline_stock,
            "offline_price": product.offline_price,
            "naver_stock": product.naver_stock,
            "naver_sale_price": product.naver_sale_price,
            "naver_image_url": product.naver_image_url,
            "pending_online_orders": product.pending_online_orders,
            "warning": warning,
        }
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── 동기화 ───────────────────────────────────────────────────────────────────

@router.post("/{product_id}/sync", response_model=SyncResult, summary="단일 상품 네이버 동기화")
async def sync_product(product_id: int, db: AsyncSession = Depends(get_db)):
    product = await svc.get_product_by_id(db, product_id)
    if not product:
        raise HTTPException(404, "상품을 찾을 수 없습니다.")
    return await svc.sync_product_to_naver(db, product)


@router.post("/sync/all", response_model=BulkSyncResult, summary="미동기화 상품 전체 동기화")
async def sync_all(db: AsyncSession = Depends(get_db)):
    return await svc.sync_all_unsynced(db)


# ── 로그 ─────────────────────────────────────────────────────────────────────

@router.get("/{product_id}/logs", response_model=list[SyncLogResponse], summary="상품 동기화 로그")
async def get_product_logs(
    product_id: int,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_logs(db, product_id=product_id, limit=limit)


# ── 엑셀 일괄 등록 ──────────────────────────────────────────────────────────

@router.post("/import/excel", response_model=ExcelImportResult, summary="엑셀 파일로 상품 일괄 등록")
async def import_excel(
    file: UploadFile = File(..., description="네이버 스마트스토어 상품 목록 엑셀 파일"),
    db: AsyncSession = Depends(get_db),
):
    """
    엑셀 파일 업로드 → 채널상품번호 읽기 → 네이버 API로 원상품번호/상품명/재고 자동 조회 → DB 저장

    엑셀 형식:
    - 1~5행: 제목행 (무시)
    - 6행부터: 상품 목록
    - A열: 채널상품번호
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "엑셀 파일(.xlsx, .xls)만 업로드 가능합니다.")
    contents = await file.read()
    return await import_from_excel(db, contents)