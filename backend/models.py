from sqlmodel import SQLModel, Field
from typing import Optional

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True)
    hashed_password: str
    is_admin: bool = Field(default=False)

class Video(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: str
    title: str
    host: str
    status: str
    category: str
    finish_time: Optional[str] = None
    image_url: str
    platform: str