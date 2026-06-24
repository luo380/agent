import datetime
import hashlib

import bcrypt
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from core.config import settings
from core.db.models import User

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES


def hash_password(password: str) -> str:
    pre_hashed = hashlib.sha256(password.encode("utf-8")).hexdigest()
    hashed = bcrypt.hashpw(pre_hashed.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")



def verify_password(plain_password: str, password_hash: str) -> bool:
    pre_hashed = hashlib.sha256(plain_password.encode("utf-8")).hexdigest()
    try:
        return bcrypt.checkpw(pre_hashed.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(
    user_id: int,
    expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES,
) -> str:
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=expires_minutes
    )
    payload = {
        "sub": str(user_id),
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Token missing subject")
        return int(user_id)
    except (JWTError, ValueError) as exc:
        raise ValueError("Invalid token") from exc


def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()

def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()

def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user