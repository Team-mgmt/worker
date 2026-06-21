from sqlalchemy import Column, Integer, String, Text, Numeric, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from worker.core.database import Base

class ScanSession(Base):
    __tablename__ = "scan_sessions"

    scan_session_id = Column(Integer, primary_key=True, autoincrement=True)
    library_code = Column(String(20), nullable=False)
    room_name = Column(String(200))
    expected_shelf_start = Column(Numeric, nullable=True)
    expected_shelf_end = Column(Numeric, nullable=True)
    estimated_shelf_start = Column(Numeric, nullable=True)
    estimated_shelf_end = Column(Numeric, nullable=True)
    shelf_confidence = Column(Numeric, nullable=True)
    source_type = Column(String(20), nullable=True)
    source_path = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.current_timestamp())

    detections = relationship("Detection", back_populates="session")

class Detection(Base):
    __tablename__ = "detections"

    detection_id = Column(Integer, primary_key=True, autoincrement=True)
    scan_session_id = Column(Integer, ForeignKey("scan_sessions.scan_session_id"))
    frame_no = Column(Integer)
    detected_order = Column(Integer)
    bbox = Column(JSONB)
    ocr_raw_text = Column(Text)
    ocr_title = Column(Text)
    ocr_author = Column(Text)
    ocr_call_number = Column(Text)
    ocr_confidence = Column(Numeric, nullable=True)
    matched_book_id = Column(Integer, ForeignKey("books.book_id"), nullable=True)
    matched_holding_id = Column(Integer, ForeignKey("holdings.holding_id"), nullable=True)
    match_score = Column(Numeric, nullable=True)
    score_margin = Column(Numeric, nullable=True)
    status = Column(String(50), nullable=False, default="unmatched") # normal, suspected_misplacement, needs_review, unmatched
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.current_timestamp())

    session = relationship("ScanSession", back_populates="detections")
