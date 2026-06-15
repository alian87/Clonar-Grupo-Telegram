import asyncio
import os
import webbrowser
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

import CopiarGrupo as cg

app = FastAPI(title="Telegram Grupo Cloner")
STATIC_DIR = Path(__file__).with_name("static")


class AppState:
    def __init__(self):
        self.client: Optional[TelegramClient] = None
        self.job_running = False
        self.ws_clients: list[WebSocket] = []
        self.auth_phone: Optional[str] = None
        self.auth_phone_code_hash: Optional[str] = None


state = AppState()


async def broadcast(data: dict):
    dead = []
    for ws in state.ws_clients:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in state.ws_clients:
            state.ws_clients.remove(ws)


def sync_sink(data: dict):
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast(data))
    except RuntimeError:
        pass


async def get_client(require_auth: bool = True) -> TelegramClient:
    cfg = cg.load_config()
    if not all(k in cfg for k in ("api_id", "api_hash")):
        raise HTTPException(status_code=400, detail="Configure API ID e API HASH.")

    if state.client is None or not state.client.is_connected():
        state.client = TelegramClient(
            cg.SESSION_NAME, cfg["api_id"], cfg["api_hash"]
        )
        await state.client.connect()

    if require_auth and not await state.client.is_user_authorized():
        raise HTTPException(status_code=401, detail="Sessão não autorizada. Faça login.")

    return state.client


@app.on_event("startup")
async def on_startup():
    port = int(os.environ.get("CPGRUPO_WEB_PORT", cg.WEB_PORT))
    url = f"http://127.0.0.1:{port}"
    asyncio.get_event_loop().call_later(1.0, lambda: webbrowser.open(url))


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    state.ws_clients.append(ws)
    try:
        await ws.send_json({"type": "hello", "job_running": state.job_running})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if ws in state.ws_clients:
            state.ws_clients.remove(ws)


@app.get("/api/status")
async def api_status():
    cfg = cg.load_config()
    has_config = all(k in cfg for k in ("api_id", "api_hash"))
    connected = False
    user = None
    if has_config:
        try:
            client = await get_client(require_auth=False)
            connected = await client.is_user_authorized()
            if connected:
                me = await client.get_me()
                user = me.username or me.first_name
        except Exception:
            connected = False
    return {
        "has_config": has_config,
        "connected": connected,
        "user": user,
        "job_running": state.job_running,
        "destino_id": cfg.get("destino_id"),
    }


@app.get("/api/groups")
async def api_groups():
    client = await get_client()
    grupos = await cg.coletar_grupos(client)
    return {
        "groups": [
            {k: v for k, v in grupo.items() if k != "entity"} for grupo in grupos
        ]
    }


class ConfigIn(BaseModel):
    api_id: int
    api_hash: str


@app.post("/api/config")
async def api_save_config(body: ConfigIn):
    cfg = cg.load_config()
    cfg["api_id"] = body.api_id
    cfg["api_hash"] = body.api_hash.strip()
    cg.save_config(cfg)
    if state.client and state.client.is_connected():
        await state.client.disconnect()
    state.client = None
    return {"ok": True}


class PhoneIn(BaseModel):
    phone: str


@app.post("/api/auth/phone")
async def api_auth_phone(body: PhoneIn):
    client = await get_client(require_auth=False)
    phone = body.phone.strip()
    if not phone:
        raise HTTPException(status_code=400, detail="Informe o telefone.")
    sent = await client.send_code_request(phone)
    state.auth_phone = phone
    state.auth_phone_code_hash = sent.phone_code_hash
    return {"ok": True, "message": "Código enviado ao Telegram."}


class CodeIn(BaseModel):
    code: str
    password: Optional[str] = None


@app.post("/api/auth/code")
async def api_auth_code(body: CodeIn):
    if not state.auth_phone:
        raise HTTPException(status_code=400, detail="Envie o telefone primeiro.")
    client = await get_client(require_auth=False)
    try:
        await client.sign_in(
            state.auth_phone,
            body.code.strip(),
            phone_code_hash=state.auth_phone_code_hash,
        )
    except SessionPasswordNeededError:
        if not body.password:
            raise HTTPException(status_code=401, detail="2FA_REQUIRED")
        await client.sign_in(password=body.password)
    state.auth_phone = None
    state.auth_phone_code_hash = None
    me = await client.get_me()
    return {"ok": True, "user": me.username or me.first_name}


class CopyIn(BaseModel):
    origem_id: int
    mode: Literal["incremental", "full", "seed", "rebuild"] = "incremental"
    destino_id: Optional[int] = None
    criar_destino: bool = False
    destino_nome: str = ""
    destino_about: str = ""
    confirm_rebuild: bool = False


@app.post("/api/copy")
async def api_copy(body: CopyIn):
    if state.job_running:
        raise HTTPException(status_code=409, detail="Já existe uma cópia em andamento.")
    if body.mode == "rebuild" and not body.confirm_rebuild:
        raise HTTPException(status_code=400, detail="Confirme o recomeço (apagar destino).")
    if not body.criar_destino and body.destino_id is None:
        raise HTTPException(status_code=400, detail="Selecione ou crie um destino.")

    async def job():
        state.job_running = True
        cg.set_event_sink(sync_sink)
        try:
            await broadcast({"type": "job_start"})
            client = await get_client()
            cfg = cg.load_config()
            await cg.executar_copia(
                client,
                cfg,
                body.origem_id,
                mode=body.mode,
                destino_peer_id=body.destino_id,
                criar_destino=body.criar_destino,
                destino_nome=body.destino_nome,
                destino_about=body.destino_about,
                skip_confirm_rebuild=body.confirm_rebuild,
            )
            await broadcast({"type": "job_done"})
        except Exception as exc:
            await broadcast({"type": "job_error", "message": str(exc)})
            cg.say(f"❌ Erro ao copiar: {exc}")
        finally:
            state.job_running = False
            cg.set_event_sink(None)

    asyncio.create_task(job())
    return {"ok": True}


def _validar_sync(data) -> dict:
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="O JSON deve ser um objeto.")
    if "pairs" not in data:
        data = {"pairs": {}}
    pairs = data.get("pairs")
    if not isinstance(pairs, dict):
        raise HTTPException(status_code=400, detail="'pairs' deve ser um objeto.")
    for pair_key, pair in pairs.items():
        if not isinstance(pair, dict):
            raise HTTPException(
                status_code=400, detail=f"Par '{pair_key}' inválido."
            )
        topics = pair.get("topics", {})
        if not isinstance(topics, dict):
            raise HTTPException(
                status_code=400,
                detail=f"Tópicos do par '{pair_key}' devem ser um objeto.",
            )
        for topic_key, topic in topics.items():
            if not isinstance(topic, dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"Tópico '{topic_key}' do par '{pair_key}' inválido.",
                )
            if "last_msg_id" in topic:
                try:
                    topic["last_msg_id"] = int(topic["last_msg_id"])
                except (TypeError, ValueError):
                    raise HTTPException(
                        status_code=400,
                        detail=f"last_msg_id inválido no tópico '{topic_key}'.",
                    )
    return data


@app.get("/api/sync")
async def api_get_sync():
    """Lê cpgrupo_sync.json local; não exige sessão Telegram."""
    data = cg.load_sync()
    return {
        **data,
        "file_exists": cg.SYNC_FILE.exists(),
        "file_path": str(cg.SYNC_FILE.resolve()),
    }


@app.put("/api/sync")
async def api_put_sync(body: dict):
    if state.job_running:
        raise HTTPException(
            status_code=409,
            detail="Aguarde o fim da cópia em andamento para editar o sync.",
        )
    # Aceita corpo com ou sem metadados _file_*
    payload = {k: v for k, v in body.items() if not k.startswith("file_")}
    data = _validar_sync(payload)
    cg.save_sync(data)
    return {
        "ok": True,
        "file_exists": True,
        "file_path": str(cg.SYNC_FILE.resolve()),
    }
