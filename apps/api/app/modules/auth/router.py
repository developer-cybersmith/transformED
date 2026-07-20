"""
Auth module router.

Handles user sign-up, sign-in, profile retrieval, and onboarding completion.
JWT verification is always done locally via PyJWT — no remote auth calls.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.dependencies import CurrentUser

router = APIRouter(tags=["auth"])


# ── Request / Response models ─────────────────────────────────────────────────


class SignUpRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str


class SignInRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    user: dict[str, Any]


class OnboardingRequest(BaseModel):
    grade_level: str
    subjects: list[str]
    learning_style: str | None = None
    goals: list[str] = []


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def signup(
    body: SignUpRequest,
) -> AuthResponse:
    """Create a new user via Supabase Auth.

    TODO (Sprint 1): Delegate to auth service layer.
    """
    # TODO: call supabase.auth.sign_up(email=body.email, password=body.password)
    # TODO: create profile row in public.profiles
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.post(
    "/signin",
    response_model=AuthResponse,
    summary="Sign in with email and password",
)
async def signin(
    body: SignInRequest,
) -> AuthResponse:
    """Exchange credentials for a Supabase JWT.

    TODO (Sprint 1): Delegate to auth service layer.
    """
    # TODO: call supabase.auth.sign_in_with_password(...)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.get(
    "/me",
    summary="Get the current user's profile",
)
async def get_me(
    current_user: CurrentUser,
) -> dict[str, Any]:
    """Return the authenticated user's profile data.

    The JWT payload is verified locally — no remote call.
    """
    return {
        "id": current_user.get("sub"),
        "email": current_user.get("email"),
        "role": current_user.get("role"),
        "app_metadata": current_user.get("app_metadata", {}),
        "user_metadata": current_user.get("user_metadata", {}),
    }


@router.post(
    "/onboarding/complete",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark onboarding as complete and save preferences",
)
async def complete_onboarding(
    current_user: CurrentUser,
    body: OnboardingRequest,
) -> None:
    """Persist the user's onboarding answers and set onboarding_complete=true.

    TODO (Sprint 1): Delegate to profile service layer.
    """
    # TODO: update profiles set onboarding_complete = true, preferences = body
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")
