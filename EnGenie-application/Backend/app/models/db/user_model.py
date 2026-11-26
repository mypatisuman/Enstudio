import uuid
from sqlalchemy import TypeDecorator, LargeBinary, String
from app.models.db.base import db

class BinaryUUID(TypeDecorator):
    """
    A custom type that handles binary(16) UUID columns, representing them
    in Python as a UUID hex string, while storing them in the database
    as binary bytes. Supports fallback to legacy integer and string IDs.
    """
    impl = LargeBinary(16)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'sqlite':
            return dialect.type_descriptor(String(36))
        return dialect.type_descriptor(LargeBinary(16))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, bytes):
            return value
        if isinstance(value, uuid.UUID):
            return value.bytes

        is_sqlite = dialect is not None and dialect.name == 'sqlite'

        if isinstance(value, int):
            if is_sqlite:
                return value
            # Encode integer as bytes to prevent DB-API driver from complaining about non-bytes-like types in other DBs
            return str(value).encode('utf-8')
        if isinstance(value, str):
            # For legacy numeric string IDs, encode as bytes directly
            if value.isdigit() and len(value) < 10:
                if is_sqlite:
                    return int(value)
                return value.encode('utf-8')
            
            value_clean = value.replace('-', '')
            try:
                # UUIDs should be 32 hex characters when stripped of hyphens
                if len(value_clean) == 32:
                    return bytes.fromhex(value_clean)
                else:
                    if is_sqlite:
                        return value
                    return value.encode('utf-8')
            except ValueError:
                if is_sqlite:
                    return value
                return value.encode('utf-8')
        raise ValueError(f"Cannot bind value of type {type(value)} to BinaryUUID")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, bytes):
            # If it's a 16-byte UUID, return its hex representation
            if len(value) == 16:
                return value.hex()
            try:
                return value.decode('utf-8')
            except UnicodeDecodeError:
                return value.hex()
        if isinstance(value, int):
            return str(value)
        return str(value)


class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(BinaryUUID, primary_key=True, default=uuid.uuid4)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)

    company = db.Column(db.String(120), nullable=True)
    location = db.Column(db.String(100), nullable=True)
    strategy = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(20), default='pending', nullable=False)
    role = db.Column(db.String(20), default='user', nullable=False)

    marketplace_subscription_id = db.Column(db.String(255), nullable=True, index=True)

