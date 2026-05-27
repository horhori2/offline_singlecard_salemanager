from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ── 상품 ──────────────────────────────────────────
class ProductCreate(BaseModel):
    barcode: str = Field(..., description="상품 바코드 (없으면 채널상품번호 사용)")
    name: str = Field(..., description="상품명")
    offline_stock: int = Field(0, ge=0)
    naver_stock: int = Field(0, ge=0)
    naver_channel_id: Optional[str] = Field(None, description="채널상품번호")
    naver_origin_id: Optional[str] = Field(None, description="원상품번호")
    naver_option_id: Optional[str] = Field(None, description="옵션ID (옵션상품만)")
    naver_sale_price: int = Field(0, ge=0, description="네이버 판매가")
    naver_image_url: Optional[str] = Field(None, description="네이버 상품 이미지 URL")


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    offline_stock: Optional[int] = Field(None, ge=0)
    naver_channel_id: Optional[str] = None
    naver_origin_id: Optional[str] = None
    naver_option_id: Optional[str] = None


class ProductResponse(BaseModel):
    id: int
    barcode: str
    name: str
    offline_stock: int
    offline_price: int
    naver_stock: int
    naver_channel_id: Optional[str]
    naver_origin_id: Optional[str]
    naver_option_id: Optional[str]
    naver_sale_price: int
    naver_image_url: Optional[str]
    pending_online_orders: int = 0
    naver_status_type: Optional[str] = None
    is_synced: bool
    last_synced_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 엑셀 업로드 결과 ────────────────────────────────
class ExcelImportResult(BaseModel):
    total: int
    succeeded: int
    failed: int
    skipped: int
    results: List[dict]


# ── 재고 수정 ──────────────────────────────────────
class StockAdjust(BaseModel):
    offline_stock: Optional[int] = Field(None, ge=0)
    naver_stock: Optional[int] = Field(None, ge=0)
    sync_to_naver: bool = Field(True)


class BarcodeStockUpdate(BaseModel):
    barcode: str
    quantity: int = Field(1, ge=1)
    sync_to_naver: bool = Field(True)


# ── 동기화 ──────────────────────────────────────────
class SyncResult(BaseModel):
    product_id: int
    product_name: str
    success: bool
    message: str
    naver_stock_after: Optional[int] = None


class BulkSyncResult(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: List[SyncResult]


# ── 로그 ──────────────────────────────────────────
class SyncLogResponse(BaseModel):
    id: int
    product_id: Optional[int]
    action: str
    message: str
    before_offline: Optional[int]
    after_offline: Optional[int]
    before_naver: Optional[int]
    after_naver: Optional[int]
    success: bool
    created_at: datetime

    model_config = {"from_attributes": True}
