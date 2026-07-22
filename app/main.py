"""FastAPI 進入點。統一錯誤格式:任何未攔截例外/驗證錯誤都以
{"error": {"code", "message"}} 出門——前端靠這個形狀(或非 2xx/連線失敗)觸發 Mock fallback。"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import router

app = FastAPI(title="CareerSandbox AI Service", version="0.1.0")
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={
        "error": {"code": "validation_error", "message": str(exc.errors()[:3])}
    })


@app.exception_handler(Exception)
async def on_unhandled(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={
        "error": {"code": "internal_error", "message": "服務暫時無法回應,請稍後再試"}
    })
