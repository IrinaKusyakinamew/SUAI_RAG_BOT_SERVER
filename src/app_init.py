from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from db.middleware import db_session_middleware_function, request_id_middleware_function
from endpoints.routers.agent_router import router as agent_router
from endpoints.routers.system_router import system_routes
from endpoints.routers.telegram_router import telegram_routes

app = FastAPI(title="RAG Server with SGR Agent", description="RAG Server with SGR Deep Research Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(BaseHTTPMiddleware, dispatch=db_session_middleware_function)
app.add_middleware(BaseHTTPMiddleware, dispatch=request_id_middleware_function)

app.include_router(system_routes)
app.include_router(telegram_routes)
app.include_router(agent_router)



@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"type": "error", "message": exc.detail},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"type": "error", "message": "Internal server error"},
    )
