from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_db, get_current_user
from api.schemas.auth import RegisterRequest, UserResponse, LoginRequest, LoginResponse
from core.db.models import User
from core.security import get_user_by_email, hash_password, authenticate_user, create_access_token

router = APIRouter()


@router.post("/register")
def register(
        payload: RegisterRequest,
        db: Session = Depends(get_db),
    ):
        user_email = get_user_by_email(db, payload.email)
        if user_email:
            raise HTTPException(status_code=400, detail="Email already registered")

        user = User(
            email=payload.email,
            name=payload.name,
            password_hash=hash_password(payload.password),
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        return {
            "data": UserResponse.model_validate(user)
        }


@router.post("/login")
def login(
        payload: LoginRequest,
        db: Session = Depends(get_db),
    ):
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid email or password")
    access_token = create_access_token(user.id)

    return {
        "data": LoginResponse(
            access_token=access_token,
            user=UserResponse.model_validate(user),
        )
    }


@router.get("/me", response_model=UserResponse)
def read_current_user(
        user: User = Depends(get_current_user),
    ):
        return user
