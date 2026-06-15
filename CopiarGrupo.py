import argparse
import asyncio
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient, functions, types, utils
from telethon.errors import FloodWaitError, ChatAdminRequiredError, RPCError

# ====== CONFIGURAÇÕES PADRÃO ======
CONFIG_FILE = Path(__file__).with_name("cpgrupo_config.json")
SYNC_FILE = Path(__file__).with_name("cpgrupo_sync.json")
SESSION_NAME = "session_forward"
LIST_LIMIT = 200
BATCH_SIZE = 20
SLEEP_BETWEEN = 1.5
PAUSA_ENTRE_TOPICOS = 5
# ===================================


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def load_sync():
    if SYNC_FILE.exists():
        with open(SYNC_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"pairs": {}}


def save_sync(sync_data: dict):
    with open(SYNC_FILE, "w", encoding="utf-8") as f:
        json.dump(sync_data, f, ensure_ascii=False, indent=2)


def sync_pair_key(from_entity, to_entity) -> str:
    return f"{utils.get_peer_id(from_entity)}:{utils.get_peer_id(to_entity)}"


def obter_ultimo_id_topico(sync_data, pair_key: str, topic_id: int, title_fallback: str = "") -> int:
    topics = sync_data.get("pairs", {}).get(pair_key, {}).get("topics", {})
    key = str(topic_id)
    if key in topics:
        return int(topics[key].get("last_msg_id", 0))
    if title_fallback and title_fallback in topics:
        return int(topics[title_fallback].get("last_msg_id", 0))
    return 0


def registrar_topico_sync(
    sync_data, pair_key: str, topic_id: int, title: str, last_msg_id: int
):
    pairs = sync_data.setdefault("pairs", {})
    pair = pairs.setdefault(pair_key, {"topics": {}})
    pair["topics"][str(topic_id)] = {
        "last_msg_id": last_msg_id,
        "title": title,
        "source_topic_id": topic_id,
    }
    pair["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def limpar_sync_par(sync_data, pair_key: str):
    pairs = sync_data.get("pairs", {})
    if pair_key in pairs:
        del pairs[pair_key]
        save_sync(sync_data)


def solicitar_modo_sincronizacao(sync_data, pair_key: str, destino_ja_tem_conteudo: bool) -> str:
    """
    Retorna: 'incremental', 'full', 'seed', 'rebuild' ou 'cancel'.
    """
    tem_sync = pair_key in sync_data.get("pairs", {})

    if destino_ja_tem_conteudo or tem_sync:
        print("\n📋 Como deseja continuar?")
        print("  (r) Recomeçar — APAGA os tópicos do destino e copia tudo de novo")
        if tem_sync:
            print("  (i) Incremental — copia só mensagens novas")
        print("  (s) Semear sync — registra IDs da origem sem copiar")
        print("  (a) Abortar")
        padrao = "i" if tem_sync else "r"
        while True:
            resposta = input(f"Escolha [{padrao}]: ").strip().lower()
            if not resposta:
                resposta = padrao
            if resposta == "r":
                return "rebuild"
            if resposta == "i" and tem_sync:
                return "incremental"
            if resposta == "s":
                return "seed"
            if resposta in ("a", "n"):
                return "cancel"
            print("Opção inválida.")

    print("\n📥 Primeira cópia deste par — todo o conteúdo será copiado.")
    print("   Nas próximas vezes você poderá sincronizar só o que for novo.")
    return "full"


async def apagar_todos_topicos_destino(client, to_entity):
    if not await is_forum(client, to_entity):
        print("⚠️ Destino não é um fórum com tópicos — limpeza automática não disponível.")
        return False

    topics = await listar_topicos(client, to_entity)
    if not topics:
        print("Nenhum tópico encontrado no destino.")
        return True

    print(f"\n🗑️ Apagando {len(topics)} tópico(s) do destino…")
    apagados = 0

    for topic in sorted(topics, key=lambda item: item.id, reverse=True):
        title = topic.title or "Geral"
        try:
            await client(
                functions.messages.DeleteTopicHistoryRequest(
                    peer=to_entity,
                    top_msg_id=topic.id,
                )
            )
            apagados += 1
            print(f"  ✅ Apagado: {title!r}")
            await asyncio.sleep(SLEEP_BETWEEN)
        except FloodWaitError as e:
            print(f"  FloodWait: aguardando {e.seconds}s")
            await asyncio.sleep(e.seconds + 1)
            await client(
                functions.messages.DeleteTopicHistoryRequest(
                    peer=to_entity,
                    top_msg_id=topic.id,
                )
            )
            apagados += 1
            print(f"  ✅ Apagado: {title!r}")
        except Exception as e:
            print(f"  ⚠️ Não foi possível apagar {title!r}: {e}")

    print(f"🗑️ Limpeza concluída ({apagados}/{len(topics)} tópico(s)).")
    return apagados > 0


def confirmar_recomeco(nome_destino: str) -> bool:
    print("\n⚠️  ATENÇÃO: todos os tópicos e mensagens do DESTINO serão apagados.")
    print("   Esta ação não pode ser desfeita pelo script.")
    confirma = input(
        f"Para confirmar, digite APAGAR (grupo: {nome_destino}): "
    ).strip()
    return confirma == "APAGAR"


async def destino_topico_tem_conteudo(client, entity, dest_topic_id) -> bool:
    kwargs = {"limit": 10}
    if dest_topic_id is not None and dest_topic_id != 1:
        kwargs["reply_to"] = dest_topic_id
    async for msg in client.iter_messages(entity, **kwargs):
        if not isinstance(msg, types.MessageService):
            return True
    return False


async def destino_parece_ter_copia(client, to_entity) -> bool:
    if not await is_forum(client, to_entity):
        return await destino_topico_tem_conteudo(client, to_entity, None)
    topics = await listar_topicos(client, to_entity)
    for topic in topics:
        if topic.id == 1:
            continue
        if await destino_topico_tem_conteudo(client, to_entity, topic.id):
            return True
    return False


async def obter_max_msg_id_origem(client, from_entity, source_topic_id, other_topic_ids):
    max_id = 0
    if source_topic_id is not None and source_topic_id != 1:
        iterator = client.iter_messages(from_entity, reply_to=source_topic_id)
    else:
        iterator = client.iter_messages(from_entity)
    async for msg in iterator:
        if source_topic_id is not None:
            if not _mensagem_no_topico(msg, source_topic_id, other_topic_ids):
                continue
        if isinstance(msg, types.MessageService):
            continue
        max_id = max(max_id, msg.id)
    return max_id


async def semear_sync_da_origem(client, from_entity, to_entity, sync_data):
    pair_key = sync_pair_key(from_entity, to_entity)
    topics = await listar_topicos(client, from_entity)
    other_topic_ids = {t.id for t in topics if t.id != 1}
    print("\n🌱 Semeando sync a partir da origem (sem copiar mensagens)…")

    if not topics:
        max_id = await obter_max_msg_id_origem(client, from_entity, 1, set())
        registrar_topico_sync(sync_data, pair_key, 1, "Geral", max_id)
        print(f"  Geral: último id registrado = {max_id}")
    else:
        for topic in topics:
            title = topic.title or "Geral"
            max_id = await obter_max_msg_id_origem(
                client, from_entity, topic.id, other_topic_ids
            )
            registrar_topico_sync(sync_data, pair_key, topic.id, title, max_id)
            print(f"  {title!r}: último id registrado = {max_id}")

    save_sync(sync_data)
    print("✅ Sync inicializado. Nas próximas execuções use modo incremental (s).")


def first_time_setup(existing_cfg=None):
    cfg = existing_cfg or {}
    print("\n=== Configuração inicial (será salva em cpgrupo_config.json) ===")

    while True:
        v = input("Informe seu API ID (número criado em my.telegram.org): ").strip()
        if v.isdigit():
            cfg["api_id"] = int(v)
            break
        print("API ID deve ser um número inteiro.")

    v = input("Informe seu API HASH (texto criado em my.telegram.org): ").strip()
    while not v or " " in v:
        print("API HASH inválido (não use espaços).")
        v = input("Informe seu API HASH novamente: ").strip()
    cfg["api_hash"] = v

    save_config(cfg)
    print("✅ Configuração salva em", CONFIG_FILE.name)
    return cfg


def ensure_config(reset=False):
    cfg = load_config()
    if reset:
        cfg = {}
    if not all(k in cfg for k in ("api_id", "api_hash")):
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
        async for d in client.iter_dialogs(limit=LIST_LIMIT):
            if d.name.strip().lower() == s.lower():
                return d.entity
        raise


async def coletar_grupos(client):
    """Lista grupos/supergrupos da conta com ID e tipo."""
    grupos = []
    async for dialog in client.iter_dialogs():
        if not dialog.is_group:
            continue
        entity = dialog.entity
        peer_id = utils.get_peer_id(entity)
        nome = dialog.name or "Sem nome"
        com_topicos = bool(getattr(entity, "forum", False))
        grupos.append(
            {
                "peer_id": peer_id,
                "nome": nome,
                "tipo": "Fórum" if com_topicos else "Grupo",
                "entity": entity,
            }
        )
    grupos.sort(key=lambda item: item["nome"].casefold())
    return grupos


def exibir_grupos(grupos):
    if not grupos:
        print("\nNenhum grupo encontrado na sua conta.")
        return

    print(f"\n{'─' * 76}")
    print(f"{'#':>3}  {'ID':<20}  {'Tipo':<8}  Nome")
    print(f"{'─' * 76}")
    for indice, grupo in enumerate(grupos, 1):
        print(f"{indice:>3}  {grupo['peer_id']:<20}  {grupo['tipo']:<8}  {grupo['nome']}")
    print(f"{'─' * 76}")
    print(f"Total: {len(grupos)} grupo(s)")
    print("Use o número (#), o ID (-100...) ou o nome exato para selecionar.\n")


LISTAR_COMANDOS = {"listar", "lista", "?", "l"}


async def solicitar_grupo(client, titulo: str, grupos=None, permitir_vazio=False, valor_vazio=None):
    while True:
        entrada = input(
            f"\n{titulo}\n"
            f"  (# da lista, ID -100..., @username, nome exato ou 'listar')\n"
            f"> "
        ).strip()

        if not entrada:
            if permitir_vazio and valor_vazio is not None:
                return await client.get_entity(valor_vazio)
            if grupos is None:
                print("Carregando grupos…")
                grupos = await coletar_grupos(client)
            exibir_grupos(grupos)
            continue

        if entrada.lower() in LISTAR_COMANDOS:
            if grupos is None:
                print("Carregando grupos…")
                grupos = await coletar_grupos(client)
            exibir_grupos(grupos)
            continue

        if entrada.isdigit() and grupos and not entrada.startswith("-"):
            indice = int(entrada)
            if 1 <= indice <= len(grupos):
                escolhido = grupos[indice - 1]
                print(f"Selecionado: {escolhido['nome']} ({escolhido['peer_id']})")
                return escolhido["entity"]

        try:
            entity = await resolve_entity(client, entrada)
            peer_id = utils.get_peer_id(entity)
            nome = getattr(entity, "title", None) or getattr(entity, "first_name", entrada)
            print(f"Selecionado: {nome} ({peer_id})")
            return entity
        except Exception as exc:
            print(f"❌ Não encontrado: {exc}")
            print("Digite 'listar' para ver todos os grupos com ID.")


async def is_forum(client, entity) -> bool:
    if getattr(entity, "forum", False):
        return True
    try:
        full = await client(functions.channels.GetFullChannelRequest(channel=entity))
        chat = next((c for c in full.chats if c.id == entity.id), entity)
        return bool(getattr(chat, "forum", False))
    except Exception:
        return False


async def ensure_forum_enabled(client, entity):
    if await is_forum(client, entity):
        return entity
    print("⚙️ Ativando tópicos no grupo de destino…")
    await client(functions.channels.ToggleForumRequest(channel=entity, enabled=True))
    return await client.get_entity(entity)


async def criar_supergrupo_forum(client, title: str, about: str = ""):
    result = await client(
        functions.channels.CreateChannelRequest(
            title=title[:128],
            about=(about or "")[:255],
            megagroup=True,
            forum=True,
        )
    )
    channel = next((c for c in result.chats if isinstance(c, types.Channel)), None)
    if channel is None:
        raise RuntimeError("Não foi possível criar o supergrupo.")
    entity = await client.get_entity(channel)
    peer_id = utils.get_peer_id(entity)
    print(f"✅ Supergrupo criado: {title!r}")
    print(f"   ID: {peer_id}")
    return entity


async def resolver_destino_interativo(client, cfg, origem_entity, grupos=None):
    origem_title = getattr(origem_entity, "title", None) or "Grupo"
    default_name = f"{origem_title} (Cópia)"[:128]

    while True:
        criar = input(
            "\nDeseja CRIAR um novo supergrupo com tópicos como destino? (s/n): "
        ).strip().lower()

        if criar == "s":
            nome = input(f"Nome do novo supergrupo [{default_name}]: ").strip() or default_name
            about = input("Descrição do grupo (opcional, Enter para pular): ").strip()
            return await criar_supergrupo_forum(client, nome, about)

        if criar == "n":
            destino_saved = cfg.get("destino_id")
            if grupos is None:
                grupos = await coletar_grupos(client)
            exibir_grupos(grupos)
            entity = await solicitar_grupo(
                client,
                "Selecione o grupo DESTINO:",
                grupos=grupos,
                permitir_vazio=bool(destino_saved),
                valor_vazio=destino_saved,
            )
            cfg["destino_id"] = utils.get_peer_id(entity)
            save_config(cfg)
            return await ensure_forum_enabled(client, entity)

        print("Responda s ou n.")


async def listar_topicos(client, channel):
    topics = []
    offset_topic = 0
    offset_id = 0
    offset_date = None

    while True:
        result = await client(
            functions.messages.GetForumTopicsRequest(
                peer=channel,
                offset_date=offset_date,
                offset_id=offset_id,
                offset_topic=offset_topic,
                limit=100,
            )
        )
        if not result.topics:
            break

        for topic in result.topics:
            if isinstance(topic, types.ForumTopic):
                topics.append(topic)

        if len(result.topics) < 100:
            break

        last = result.topics[-1]
        if not isinstance(last, types.ForumTopic):
            break
        offset_topic = last.id
        offset_id = last.top_message
        offset_date = last.date

    return topics


async def _extrair_top_msg_id(res):
    for update in res.updates:
        if isinstance(update, (types.UpdateNewMessage, types.UpdateNewChannelMessage)):
            return update.message.id
    return None


async def buscar_topico_por_titulo(client, channel, title: str):
    result = await client(
        functions.messages.GetForumTopicsRequest(
            peer=channel,
            q=title[:35],
            offset_date=None,
            offset_id=0,
            offset_topic=0,
            limit=100,
        )
    )
    for topic in result.topics:
        if isinstance(topic, types.ForumTopic) and topic.title == title:
            return topic
    return None


async def criar_topico(
    client,
    channel,
    title: str,
    icon_color=None,
    icon_emoji_id=None,
    closed=False,
):
    kwargs = {
        "peer": channel,
        "title": title[:128],
        "random_id": random.randrange(1, 2**63),
    }
    if icon_emoji_id:
        kwargs["icon_emoji_id"] = icon_emoji_id
    elif icon_color:
        kwargs["icon_color"] = icon_color

    res = await client(functions.messages.CreateForumTopicRequest(**kwargs))
    created_id = await _extrair_top_msg_id(res)

    topic = await buscar_topico_por_titulo(client, channel, title)
    if topic is None:
        if created_id is None:
            raise RuntimeError(f"Não foi possível criar o tópico {title!r}.")
        topic_id = created_id
    else:
        topic_id = topic.id

    if closed and topic_id and topic_id != 1:
        try:
            await client(
                functions.messages.EditForumTopicRequest(
                    peer=channel,
                    topic_id=topic_id,
                    closed=True,
                )
            )
        except Exception as e:
            print(f"  ⚠️ Não foi possível fechar o tópico {title!r}: {e}")

    return topic_id


def _mensagem_no_topico(msg, topic_id: int, other_topic_ids: set) -> bool:
    """Verifica se uma mensagem pertence ao tópico indicado."""
    if isinstance(msg, types.MessageService):
        return False

    if topic_id != 1:
        reply = msg.reply_to
        if reply is None:
            return False
        if getattr(reply, "forum_topic", False):
            top = getattr(reply, "reply_to_top_id", None)
            if top is not None:
                return top == topic_id
            return reply.reply_to_msg_id == topic_id
        return False

    reply = msg.reply_to
    if reply is None:
        return True
    if not getattr(reply, "forum_topic", False):
        return True
    top = getattr(reply, "reply_to_top_id", None)
    if top is not None:
        return top == 1
    reply_id = getattr(reply, "reply_to_msg_id", None)
    return reply_id == 1 or reply_id not in other_topic_ids


async def preparar_topico_destino(client, to_entity, source_topic, dest_topics_by_id):
    title = source_topic.title or "Geral"
    closed = bool(getattr(source_topic, "closed", False))
    icon_color = getattr(source_topic, "icon_color", None)
    icon_emoji_id = getattr(source_topic, "icon_emoji_id", None)

    if source_topic.id == 1:
        dest_general = dest_topics_by_id.get(1)
        if dest_general is None:
            raise RuntimeError("Tópico Geral não encontrado no destino.")

        if title and title != (dest_general.title or ""):
            try:
                await client(
                    functions.messages.EditForumTopicRequest(
                        peer=to_entity,
                        topic_id=1,
                        title=title[:128],
                    )
                )
            except Exception as e:
                print(f"  ⚠️ Não foi possível renomear o tópico Geral: {e}")

        if closed:
            try:
                await client(
                    functions.messages.EditForumTopicRequest(
                        peer=to_entity,
                        topic_id=1,
                        closed=True,
                    )
                )
            except Exception as e:
                print(f"  ⚠️ Não foi possível fechar o tópico Geral: {e}")

        return None

    existing = await buscar_topico_por_titulo(client, to_entity, title)
    if existing:
        print(f"  ↪ Tópico já existe no destino, reutilizando: {title!r}")
        return existing.id

    return await criar_topico(
        client,
        to_entity,
        title,
        icon_color=icon_color,
        icon_emoji_id=icon_emoji_id,
        closed=closed,
    )


async def encaminhar_lote(client, from_entity, to_entity, ids_buffer, top_msg_id):
    kwargs = dict(
        from_peer=from_entity,
        id=ids_buffer,
        to_peer=to_entity,
        drop_author=True,
        noforwards=False,
        silent=False,
    )
    if top_msg_id is not None:
        kwargs["top_msg_id"] = top_msg_id
    await client(functions.messages.ForwardMessagesRequest(**kwargs))


def _segundos_flood(exc) -> int:
    seconds = getattr(exc, "seconds", None)
    if seconds:
        return int(seconds)
    match = re.search(r"wait of (\d+) seconds", str(exc), re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 60


async def aguardar_flood(exc):
    seconds = _segundos_flood(exc)
    minutos = seconds // 60
    resto = seconds % 60
    if minutos:
        print(f"  ⏳ FloodWait: aguardando {seconds}s (~{minutos} min {resto}s)…")
    else:
        print(f"  ⏳ FloodWait: aguardando {seconds}s…")
    await asyncio.sleep(seconds + 1)


async def encaminhar_com_retry(client, from_entity, to_entity, ids_buffer, top_msg_id):
    while True:
        try:
            await encaminhar_lote(client, from_entity, to_entity, ids_buffer, top_msg_id)
            return
        except FloodWaitError as exc:
            await aguardar_flood(exc)
        except RPCError as exc:
            if "wait" in str(exc).lower() and "seconds" in str(exc).lower():
                await aguardar_flood(exc)
            else:
                raise


async def copiar_mensagens_topico(
    client,
    from_entity,
    to_entity,
    source_topic_id,
    dest_top_id,
    other_topic_ids=None,
    min_msg_id=0,
):
    total = 0
    max_copied_id = min_msg_id
    ids_buffer = []
    other_topic_ids = other_topic_ids or set()

    if source_topic_id is not None and source_topic_id != 1:
        message_iter = client.iter_messages(
            from_entity, reply_to=source_topic_id, reverse=True
        )
    else:
        message_iter = client.iter_messages(from_entity, reverse=True)

    async def enviar_buffer():
        nonlocal total, max_copied_id, ids_buffer
        if not ids_buffer:
            return
        lote = ids_buffer[:]
        await encaminhar_com_retry(client, from_entity, to_entity, lote, dest_top_id)
        total += len(lote)
        max_copied_id = max(max_copied_id, max(lote))
        print(f"  {total} mensagens encaminhadas…")
        ids_buffer.clear()
        await asyncio.sleep(SLEEP_BETWEEN)

    async for msg in message_iter:
        if isinstance(msg, types.MessageService):
            continue
        if source_topic_id is not None:
            if not _mensagem_no_topico(msg, source_topic_id, other_topic_ids):
                continue
        if msg.id <= min_msg_id:
            continue

        ids_buffer.append(msg.id)
        if len(ids_buffer) < BATCH_SIZE:
            continue

        try:
            await enviar_buffer()
        except Exception as e:
            print(f"  Erro em lote -> {e}")
            for mid in ids_buffer[:]:
                try:
                    await encaminhar_com_retry(
                        client, from_entity, to_entity, [mid], dest_top_id
                    )
                    total += 1
                    max_copied_id = max(max_copied_id, mid)
                except Exception as e2:
                    print(f"  Erro id {mid} -> {e2}")
            ids_buffer.clear()

    if ids_buffer:
        try:
            await enviar_buffer()
        except Exception as e:
            print(f"  Erro no envio final -> {e}")
            for mid in ids_buffer[:]:
                try:
                    await encaminhar_com_retry(
                        client, from_entity, to_entity, [mid], dest_top_id
                    )
                    total += 1
                    max_copied_id = max(max_copied_id, mid)
                except Exception as e2:
                    print(f"  Erro id {mid} -> {e2}")

    return total, max_copied_id


async def copiar_comunidade_forum(client, from_entity, to_entity, incremental=False, sync_data=None):
    sync_data = sync_data if sync_data is not None else load_sync()
    pair_key = sync_pair_key(from_entity, to_entity)
    to_entity = await ensure_forum_enabled(client, to_entity)
    topics = await listar_topicos(client, from_entity)

    if not topics:
        print("⚠️ Nenhum tópico encontrado na origem. Copiando mensagens no tópico Geral…")
        title = "Geral"
        min_id = obter_ultimo_id_topico(sync_data, pair_key, 1, title) if incremental else 0
        if incremental and min_id:
            print(f"  Última mensagem copiada: id {min_id}")
        elif incremental and min_id == 0 and await destino_topico_tem_conteudo(client, to_entity, None):
            print("  ⚠️ Destino já tem mensagens sem histórico de sync. Pulando para evitar duplicatas.")
            print("  Use a opção 'semear sync' na próxima execução.")
            return
        total, max_id = await copiar_mensagens_topico(
            client, from_entity, to_entity, 1, None, set(), min_msg_id=min_id
        )
        registrar_topico_sync(sync_data, pair_key, 1, title, max_id)
        save_sync(sync_data)
        if total == 0 and incremental:
            print("  Nenhuma mensagem nova.")
        print(f"\n✅ Cópia concluída. Total: {total} mensagem(ns)\n")
        return

    dest_topics = await listar_topicos(client, to_entity)
    dest_topics_by_id = {t.id: t for t in dest_topics}
    other_topic_ids = {t.id for t in topics if t.id != 1}

    print(f"\n📋 {len(topics)} tópico(s) encontrado(s) na origem.")
    if incremental:
        print("🔄 Modo incremental: copiando apenas mensagens novas por tópico.")
    grand_total = 0

    for index, topic in enumerate(topics, 1):
        title = topic.title or "Geral"
        print(f"\n[{index}/{len(topics)}] Tópico: {title!r}")

        min_id = obter_ultimo_id_topico(sync_data, pair_key, topic.id, title) if incremental else 0
        if incremental and min_id:
            print(f"  Última mensagem copiada: id {min_id}")

        try:
            dest_top_id = await preparar_topico_destino(
                client, to_entity, topic, dest_topics_by_id
            )
            print(f"  top_msg_id destino = {dest_top_id!r}")
        except ChatAdminRequiredError:
            print("  ⚠️ Sem permissão para criar/editar tópicos. Pulando.")
            continue
        except Exception as e:
            print(f"  ❌ Erro ao preparar tópico: {e}")
            continue

        if incremental and min_id == 0:
            tem_conteudo = await destino_topico_tem_conteudo(
                client, to_entity, dest_top_id if topic.id != 1 else None
            )
            if tem_conteudo:
                print("  ⚠️ Tópico já tem mensagens no destino sem histórico de sync.")
                print("  Pulando para evitar duplicatas. Use 'semear sync' na próxima execução.")
                continue

        print("  Iniciando cópia…")
        try:
            total, max_id = await copiar_mensagens_topico(
                client,
                from_entity,
                to_entity,
                topic.id,
                dest_top_id,
                other_topic_ids,
                min_msg_id=min_id,
            )
            registrar_topico_sync(sync_data, pair_key, topic.id, title, max_id)
            save_sync(sync_data)
            grand_total += total
            if total == 0 and incremental:
                print("  Nenhuma mensagem nova.")
            else:
                print(f"  ✅ Tópico concluído: {total} mensagem(ns)")
        except Exception as e:
            print(f"  ❌ Erro ao copiar tópico: {e}")

        if index < len(topics):
            await asyncio.sleep(PAUSA_ENTRE_TOPICOS)

    print(f"\n✅ Comunidade sincronizada. Total geral: {grand_total} mensagem(ns)\n")


async def get_or_create_topic(client, channel, title: str) -> int:
    existing = await buscar_topico_por_titulo(client, channel, title)
    if existing:
        return existing.id
    return await criar_topico(client, channel, title)


async def copiar_grupo_simples(
    client, from_entity, to_entity, incremental=False, sync_data=None
):
    sync_data = sync_data if sync_data is not None else load_sync()
    pair_key = sync_pair_key(from_entity, to_entity)
    origem_title = getattr(from_entity, "title", None) or getattr(
        from_entity, "first_name", "Origem"
    )
    topic_title = origem_title[:128]
    print(f"Tópico no destino: {topic_title!r}")

    try:
        to_entity = await ensure_forum_enabled(client, to_entity)
        top_msg_id = await get_or_create_topic(client, to_entity, topic_title)
        print(f"top_msg_id = {top_msg_id}")
    except ChatAdminRequiredError:
        print("⚠️ Sem permissão para criar tópicos no destino. Encaminhando SEM tópico.")
        top_msg_id = None

    min_id = obter_ultimo_id_topico(sync_data, pair_key, 0, topic_title) if incremental else 0
    if incremental and min_id:
        print(f"Última mensagem copiada: id {min_id}")
        print("🔄 Modo incremental: copiando apenas mensagens novas.")
    elif incremental and min_id == 0 and await destino_topico_tem_conteudo(client, to_entity, top_msg_id):
        print("⚠️ Destino já tem mensagens sem histórico de sync. Pulando para evitar duplicatas.")
        return

    print("Iniciando cópia…")
    total, max_id = await copiar_mensagens_topico(
        client, from_entity, to_entity, None, top_msg_id, min_msg_id=min_id
    )
    registrar_topico_sync(sync_data, pair_key, 0, topic_title, max_id)
    save_sync(sync_data)
    if total == 0 and incremental:
        print("Nenhuma mensagem nova.")
    print(f"✅ Encaminhamento concluído. Total: {total}\n")


async def copiar_origem(client, from_entity, to_entity, mode="full"):
    sync_data = load_sync()
    pair_key = sync_pair_key(from_entity, to_entity)

    if mode == "seed":
        await semear_sync_da_origem(client, from_entity, to_entity, sync_data)
        return

    if mode == "rebuild":
        nome_destino = getattr(to_entity, "title", None) or "destino"
        if not confirmar_recomeco(nome_destino):
            print("Operação cancelada.")
            return
        await apagar_todos_topicos_destino(client, to_entity)
        limpar_sync_par(sync_data, pair_key)
        mode = "full"

    incremental = mode == "incremental"
    if await is_forum(client, from_entity):
        print("📂 Origem detectada como comunidade com tópicos.")
        await copiar_comunidade_forum(
            client, from_entity, to_entity, incremental=incremental, sync_data=sync_data
        )
    else:
        print("💬 Origem detectada como grupo/chat simples.")
        await copiar_grupo_simples(
            client, from_entity, to_entity, incremental=incremental, sync_data=sync_data
        )


async def main(reset=False, reset_sync=False):
    if reset_sync and SYNC_FILE.exists():
        SYNC_FILE.unlink()
        print("✅ Histórico de sync apagado (cpgrupo_sync.json).")

    cfg = ensure_config(reset=reset)
    api_id = cfg["api_id"]
    api_hash = cfg["api_hash"]

    async with TelegramClient(SESSION_NAME, api_id, api_hash) as client:
        me = await client.get_me()
        print("\nConectado como", me.username or me.first_name)
        print("Dica: pressione Enter ou digite 'listar' para ver seus grupos com ID.")

        while True:
            try:
                grupos = await coletar_grupos(client)
                exibir_grupos(grupos)
                from_entity = await solicitar_grupo(
                    client,
                    "Selecione a ORIGEM a copiar:",
                    grupos=grupos,
                )
                to_entity = await resolver_destino_interativo(client, cfg, from_entity, grupos)
                sync_data = load_sync()
                pair_key = sync_pair_key(from_entity, to_entity)
                destino_tem_conteudo = await destino_parece_ter_copia(client, to_entity)
                mode = solicitar_modo_sincronizacao(sync_data, pair_key, destino_tem_conteudo)
                if mode == "cancel":
                    print("Operação cancelada.")
                    continue
                await copiar_origem(client, from_entity, to_entity, mode=mode)
            except Exception as e:
                print(f"❌ Erro ao copiar: {e}")

            repetir = input("\nDeseja copiar outro grupo? (s/n): ").strip().lower()
            if repetir != "s":
                print("Encerrando execução. 👋")
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Clonar comunidades/grupos do Telegram com suporte a tópicos."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Refazer configuração (API ID/HASH).",
    )
    parser.add_argument(
        "--reset-sync",
        action="store_true",
        help="Apagar histórico de sincronização incremental (cpgrupo_sync.json).",
    )
    args = parser.parse_args()
    asyncio.run(main(reset=args.reset, reset_sync=args.reset_sync))
