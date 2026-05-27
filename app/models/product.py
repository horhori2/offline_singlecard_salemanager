from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Integer, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    barcode: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # 오프라인 재고
    offline_stock: Mapped[int] = mapped_column(Integer, default=0)
    offline_price: Mapped[int] = mapped_column(Integer, default=0)

    # 네이버 스마트스토어 연동 정보
    naver_channel_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    naver_origin_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    naver_option_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    naver_stock: Mapped[int] = mapped_column(Integer, default=0)
    naver_sale_price: Mapped[int] = mapped_column(Integer, default=0)
    naver_image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    naver_status_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # 온라인 주문 대기 수량 (바코드 스캔 시 경고용)
    pending_online_orders: Mapped[int] = mapped_column(Integer, default=0)

    # 동기화 상태
    is_synced: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    logs: Mapped[List[SyncLog]] = relationship("SyncLog", back_populates="product", cascade="all, delete-orphan")
    order_logs: Mapped[List[OnlineOrderLog]] = relationship("OnlineOrderLog", back_populates="product", cascade="all, delete-orphan")


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    before_offline: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    after_offline: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    before_naver: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    after_naver: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    product: Mapped[Optional[Product]] = relationship("Product", back_populates="logs")


class OfflineOrder(Base):
    """오프라인 POS 주문"""
    __tablename__ = "offline_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    total_qty: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    items: Mapped[List[OfflineOrderItem]] = relationship("OfflineOrderItem", back_populates="order", cascade="all, delete-orphan")


class OfflineOrderItem(Base):
    """오프라인 주문 상품 항목"""
    __tablename__ = "offline_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("offline_orders.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    product_name: Mapped[str] = mapped_column(String(200), default="")
    barcode: Mapped[str] = mapped_column(String(50), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[int] = mapped_column(Integer, default=0)
    subtotal: Mapped[int] = mapped_column(Integer, default=0)

    order: Mapped[OfflineOrder] = relationship("OfflineOrder", back_populates="items")


class OnlineOrderLog(Base):
    """네이버 온라인 주문 수집 로그"""
    __tablename__ = "online_order_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    product_order_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    order_status: Mapped[str] = mapped_column(String(50))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    product_name: Mapped[str] = mapped_column(String(200), default="")
    product_class: Mapped[str] = mapped_column(String(50), default="")
    unit_price: Mapped[int] = mapped_column(Integer, default=0)
    delivery_method: Mapped[str] = mapped_column(String(50), default="")
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    product: Mapped[Optional[Product]] = relationship("Product", back_populates="order_logs")
