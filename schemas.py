from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class MessageStatus(str, Enum):
    sent = "sent"
    received = "received"
    read = "read"


# --- Auth ---

class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: str
    username: str


# --- Messages ---

class ReplyTo(BaseModel):
    message_id: str
    sender_id: str
    sender_username: str = ""
    content: Optional[str] = None
    is_media: bool = False


class MessageCreate(BaseModel):
    receiver_id: str
    content: Optional[str] = None
    media_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    is_media: bool = False
    reply_to: Optional[ReplyTo] = None


class MessageResponse(BaseModel):
    id: str
    sender_id: str
    receiver_id: str
    content: Optional[str] = None
    media_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    status: MessageStatus
    is_media: bool
    sent_at: datetime
    received_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    reply_to: Optional[ReplyTo] = None


class StatusUpdate(BaseModel):
    message_ids: List[str]
    status: MessageStatus


# --- Albums ---

class SaveToAlbum(BaseModel):
    album_id: str
    media_url: str
    thumbnail_url: Optional[str] = None
    filename: str = "saved_media"
    media_type: str = "application/octet-stream"
    is_video: bool = False


class AlbumResponse(BaseModel):
    id: str
    name: str


class AlbumAuth(BaseModel):
    album_id: str
    password: str


class AlbumFileResponse(BaseModel):
    id: str
    album_id: str
    filename: str
    media_url: str
    thumbnail_url: Optional[str] = None
    media_type: str
    is_video: bool
    file_size: int
    uploaded_at: datetime
