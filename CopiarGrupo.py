# cpgrupo_origem_cfg.py
import json
import argparse
from pathlib import Path
import asyncio
from telethon import TelegramClient, functions, types
from telethon.errors import FloodWaitError, ChatAdminRequiredError

# ====== CONFIGURAÇÕES PADRÃO ======
CONFIG_FILE = Path(__file__).with_name("cpgrupo_config.json")
SESSION_NAME = "session_forward"
LIST_LIMIT = 200
BATCH_SIZE = 50
SLEEP_BETWEEN = 0.2
# ===================================

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def first_time_setup(existing_cfg=None):
    cfg = existing_cfg or {}
    print("\n=== Configuração inicial (será salva em cpgrupo_config.json) ===")
    # api_id
    while True:
        v = input("Informe seu API ID (número criado em my.telegram.org): ").strip()
        if v.isdigit():
            cfg["api_id"] = int(v)
            break
        print("API ID deve ser um número inteiro.")

    # api_hash (VISÍVEL)
    v = input("Informe seu API HASH (texto criado em my.telegram.org): ").strip()
    while not v or " " in v:
        print("API HASH inválido (não use espaços).")
        v = input("Informe seu API HASH novamente: ").strip()
    cfg["api_hash"] = v

    # destino
    while True:
        d = input("Informe o ID do GRUPO DESTINO (formato -100xxxxxxxxxx): ").strip()
        if (d.startswith("-") and d[1:].isdigit()) or d.isdigit():
            cfg["destino_id"] = int(d)
            break
        print("ID inválido. Ex: -1001234567890")

    save_config(cfg)
    print("✅ Configuração salva em", CONFIG_FILE.name)
    return cfg

def ensure_config(reset=False):
    cfg = load_config()
    if reset or not all(k in cfg for k in ("api_id", "api_hash", "destino_id")):
        cfg = first_time_setup(cfg)
    return cfg

async def resolve_entity(client, s: str):
    s = s.strip()
    if (s.startswith("-") and s[1:].isdigit()) or s.isdigit():
        return await client.get_entity(int(s))
    if s.startswith("@"):
        s = s[1:]
    try:
        return await client.get_entity(s)
    except Exception:
        # fallback por nome exato
        async for d in client.iter_dialogs(limit=LIST_LIMIT):
            if d.name.strip().lower() == s.lower():
                return d.entity
        raise

async def get_or_create_topic(client, channel, title: str) -> int:
    """Cria (ou encontra) um tópico e retorna o top_msg_id"""
    topics = await client(functions.channels.GetForumTopicsRequest(
        channel=channel, q=title[:35], offset_date=0, offset_id=0,
        offset_topic=0, limit=100
    ))
    for t in topics.topics:
        if getattr(t, 'title', '') == title:
            return t.top_message

    res = await client(functions.channels.CreateForumTopicRequest(
        channel=channel, title=title[:128], icon_color=None, icon_emoji_id=None
    ))
    top_msg_id = None
    for u in res.updates:
        if isinstance(u, (types.UpdateNewMessage, types.UpdateNewChannelMessage)):
            top_msg_id = u.message.id
            break

    if top_msg_id is None:
        topics2 = await client(functions.channels.GetForumTopicsRequest(
            channel=channel, q=title[:35], offset_date=0, offset_id=0,
            offset_topic=0, limit=100
        ))
        for t in topics2.topics:
            if getattr(t, 'title', '') == title:
                top_msg_id = t.top_message
                break

    if top_msg_id is None:
        raise RuntimeError("Não foi possível obter o top_msg_id do tópico.")
    return top_msg_id

async def copiar_grupo(client, from_entity, to_entity):
    origem_title = getattr(from_entity, 'title', None) or getattr(from_entity, 'first_name', 'Origem')
    topic_title = origem_title[:128]
    print(f"Tópico no destino: {topic_title!r}")

    try:
        top_msg_id = await get_or_create_topic(client, to_entity, topic_title)
        print(f"top_msg_id = {top_msg_id}")
    except ChatAdminRequiredError:
        print("⚠️ Sem permissão para criar tópicos no destino. Encaminhando SEM tópico.")
        top_msg_id = None

    print("Iniciando cópia…")
    total = 0
    ids_buffer = []

    async for msg in client.iter_messages(from_entity, reverse=True):
        ids_buffer.append(msg.id)
        if len(ids_buffer) >= BATCH_SIZE:
            try:
                await client(functions.messages.ForwardMessagesRequest(
                    from_peer=from_entity,
                    id=ids_buffer,
                    to_peer=to_entity,
                    drop_author=True,
                    noforwards=False,
                    silent=False,
                    top_msg_id=top_msg_id
                ))
                total += len(ids_buffer)
                print(f"{total} mensagens encaminhadas…")
                ids_buffer.clear()
                await asyncio.sleep(SLEEP_BETWEEN)
            except FloodWaitError as e:
                print(f"FloodWait: aguardando {e.seconds}s")
                await asyncio.sleep(e.seconds + 1)
            except Exception as e:
                print("Erro em lote ->", e)
                # tenta individualmente
                for mid in ids_buffer:
                    try:
                        await client(functions.messages.ForwardMessagesRequest(
                            from_peer=from_entity,
                            id=[mid],
                            to_peer=to_entity,
                            drop_author=True,
                            noforwards=False,
                            silent=False,
                            top_msg_id=top_msg_id
                        ))
                        total += 1
                    except Exception as e2:
                        print(f"Erro id {mid} ->", e2)
                ids_buffer.clear()

    # envia o restante
    if ids_buffer:
        try:
            await client(functions.messages.ForwardMessagesRequest(
                from_peer=from_entity,
                id=ids_buffer,
                to_peer=to_entity,
                drop_author=True,
                noforwards=False,
                silent=False,
                top_msg_id=top_msg_id
            ))
            total += len(ids_buffer)
            print(f"{total} mensagens encaminhadas…")
        except Exception as e:
            print("Erro no envio final ->", e)

    print(f"✅ Encaminhamento concluído. Total: {total}\n")

async def main(reset=False):
    cfg = ensure_config(reset=reset)
    api_id = cfg["api_id"]
    api_hash = cfg["api_hash"]
    DESTINO_ID = cfg["destino_id"]

    async with TelegramClient(SESSION_NAME, api_id, api_hash) as client:
        me = await client.get_me()
        print("\nConectado como", me.username or me.first_name)

        to_entity = await client.get_entity(DESTINO_ID)

        while True:
            src = input("\nInforme o ID (-100...), @username, ou nome exato do chat de ORIGEM: ").strip()
            try:
                from_entity = await resolve_entity(client, src)
                await copiar_grupo(client, from_entity, to_entity)
            except Exception as e:
                print(f"❌ Erro ao copiar grupo: {e}")

            repetir = input("\nDeseja copiar outro grupo? (s/n): ").strip().lower()
            if repetir != "s":
                print("Encerrando execução. 👋")
                break

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copiar mensagens de um chat para um supergrupo com tópicos.")
    parser.add_argument("--reset", action="store_true", help="Refazer configuração (API ID/HASH e destino).")
    args = parser.parse_args()
    asyncio.run(main(reset=args.reset))
