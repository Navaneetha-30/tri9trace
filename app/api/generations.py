"""Generations / retrieval API router (FR5/FR6/FR7). Filled in stages 6-8."""
from fastapi import APIRouter

router = APIRouter(prefix="/generations", tags=["generations"])