from sqlalchemy import Column, Integer, String, Text, Numeric, Date, ForeignKey, DateTime, func, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from worker.core.database import Base

class Book(Base):
    __tablename__ = "books"

    book_id = Column(Integer, primary_key=True, autoincrement=True)
    isbn13 = Column(String(20), index=True, unique=True)
    bookname = Column(Text, nullable=False)
    normalized_bookname = Column(Text)
    authors = Column(Text)
    normalized_authors = Column(Text)
    publisher = Column(Text)
    publication_year = Column(String(10))
    book_image_url = Column(Text)
    created_at = Column(DateTime, server_default=func.current_timestamp())

    holdings = relationship("Holding", back_populates="book")

    __table_args__ = (
        Index('idx_books_name_trgm', normalized_bookname, postgresql_using='gin', postgresql_ops={'normalized_bookname': 'gin_trgm_ops'}),
    )

class Holding(Base):
    __tablename__ = "holdings"

    holding_id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, ForeignKey("books.book_id"), nullable=True)
    library_code = Column(String(20), nullable=False, index=True)
    class_no = Column(String(50))
    class_no_clean = Column(String(50))
    class_no_num = Column(Numeric)
    book_code = Column(String(100))
    call_number = Column(String(200))
    normalized_call_number = Column(String(200))
    shelf_loc_code = Column(String(50))
    shelf_loc_name = Column(String(200))
    separate_shelf_code = Column(String(50))
    separate_shelf_name = Column(String(200))
    copy_code = Column(String(50))
    reg_date = Column(Date)
    created_at = Column(DateTime, server_default=func.current_timestamp())

    book = relationship("Book", back_populates="holdings")

    __table_args__ = (
        Index('idx_holdings_library_class', library_code, class_no_num),
        Index('idx_holdings_library_call_number', library_code, normalized_call_number),
    )
