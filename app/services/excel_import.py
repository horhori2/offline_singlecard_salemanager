from __future__ import annotations
"""
엑셀 파일로 상품 일괄 등록
- 6행부터 상품 목록
- A열: 채널상품번호
- 채널상품번호로 네이버 API 조회 → 원상품번호, 상품명, 판매가, 재고 자동 추출
"""
import logging
from io import BytesIO

import openpyxl
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.schemas import ExcelImportResult
from app.services.naver_client import naver_client
from app.services.inventory import get_product_by_barcode, _write_log

logger = logging.getLogger(__name__)

# 엑셀 컬럼 인덱스 (0-based)
COL_CHANNEL_ID = 0   # A열


async def import_from_excel(
    db: AsyncSession,
    file_bytes: bytes,
) -> ExcelImportResult:
    """
    엑셀 파일에서 채널상품번호를 읽어 네이버 API로 상품 정보 조회 후 DB 저장
    """
    wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
    ws = wb.active

    results = []
    succeeded = skipped = failed = 0

    # 6행(index 5)부터 읽기
    rows = list(ws.iter_rows(min_row=6, values_only=True))
    total = sum(1 for row in rows if row and row[COL_CHANNEL_ID])

    for row in rows:
        if not row or not row[COL_CHANNEL_ID]:
            continue

        channel_id = str(row[COL_CHANNEL_ID]).strip()

        try:
            # 1) 네이버 채널상품 조회
            channel_data = await naver_client.get_channel_product(channel_id)
            origin = channel_data.get("originProduct", {})

            # 2) 필요한 정보 추출
            name = origin.get("name", "")
            sale_price = origin.get("salePrice", 0)
            naver_stock = origin.get("stockQuantity", 0)
            naver_image_url = (
                origin.get("images", {})
                .get("representativeImage", {})
                .get("url", "")
            )

            # 3) 바코드: 판매자 관리코드 → 없으면 채널상품번호 사용
            barcode = (
                origin.get("detailAttribute", {})
                .get("sellerCodeInfo", {})
                .get("sellerManagementCode", "")
                or channel_id
            )

            # 4) 원상품번호 조회 (판매자 관리코드로 검색 → 빠름)
            origin_id = await _fetch_origin_id(channel_id, seller_code=barcode)

            # 5) 이미 등록된 상품인지 확인 (바코드 기준)
            existing = await get_product_by_barcode(db, barcode)
            if existing:
                # 네이버 정보만 업데이트
                existing.naver_channel_id = channel_id
                existing.naver_origin_id = origin_id
                existing.naver_stock = naver_stock
                existing.naver_sale_price = sale_price
                existing.name = name
                await db.commit()
                results.append({"channel_id": channel_id, "name": name, "status": "updated"})
                skipped += 1
                logger.info("상품 업데이트: %s (%s)", name, channel_id)
                continue

            # 6) 신규 등록
            product = Product(
                barcode=barcode,
                name=name,
                offline_stock=naver_stock,
                offline_price=sale_price,
                naver_channel_id=channel_id,
                naver_origin_id=origin_id,
                naver_stock=naver_stock,
                naver_sale_price=sale_price,
                naver_image_url=naver_image_url,
                is_synced=True,
            )
            db.add(product)
            await db.commit()
            await db.refresh(product)
            await _write_log(db, product.id, "CREATE", f"엑셀 일괄 등록: {name}")

            results.append({
                "channel_id": channel_id,
                "origin_id": origin_id,
                "name": name,
                "naver_stock": naver_stock,
                "sale_price": sale_price,
                "status": "created",
            })
            succeeded += 1
            logger.info("상품 등록: %s (채널: %s / 원상품: %s)", name, channel_id, origin_id)

        except Exception as e:
            failed += 1
            results.append({"channel_id": channel_id, "status": "failed", "error": str(e)})
            logger.error("상품 등록 실패 [%s]: %s", channel_id, e)

    wb.close()
    return ExcelImportResult(
        total=total,
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        results=results,
    )


async def _fetch_origin_id(channel_id: str, seller_code: str = "") -> str | None:
    """
    채널상품번호 → 원상품번호 조회
    1) 판매자 관리코드(바코드)로 검색 → 빠름
    2) 실패 시 채널상품 직접 조회로 fallback
    """
    # 방법 1: 판매자 관리코드로 검색 (훨씬 빠름)
    if seller_code:
        try:
            result = await naver_client.search_products_by_seller_code(seller_code)
            items = result.get("contents", [])
            if items:
                return str(items[0].get("originProductNo", ""))
        except Exception as e:
            logger.debug("판매자코드 조회 실패 [%s]: %s", seller_code, e)

    # 방법 2: 채널상품 직접 조회 후 원상품번호 추출 불가 → None 반환
    # (7000개 전체 순회는 너무 느리므로 사용하지 않음)
    # 대신 판매자 센터에서 원상품번호를 직접 확인하거나
    # 엑셀에 원상품번호 열을 추가하는 방법 권장
    logger.warning("원상품번호 조회 실패: channel_id=%s, seller_code=%s — 판매자 센터에서 직접 확인 필요", channel_id, seller_code)
    return None