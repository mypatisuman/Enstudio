from typing import Optional, List
from app.models.db.base import db
from app.models.db.user_model import User

class UserRepository:
    @staticmethod
    def get_by_email(email: str) -> Optional[User]:
        try:
            return db.session.query(User).filter_by(email=email).first()
        except Exception:
            return None
            
    @staticmethod
    def get_by_username(username: str) -> Optional[User]:
        try:
            return db.session.query(User).filter_by(username=username).first()
        except Exception:
            return None

    @staticmethod
    def get_by_id(user_id: int) -> Optional[User]:
        return db.session.get(User, user_id)

    @staticmethod
    def get_all_pending() -> List[User]:
        return db.session.query(User).filter_by(status='pending').all()
        
    @staticmethod
    def save(user: User) -> User:
        db.session.add(user)
        db.session.commit()
        return user
