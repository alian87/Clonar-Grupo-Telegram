import argparse
import asyncio
import json
import random
import re
from datetime import datetime, timedelta, timezone
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
WEB_PORT = 8765
# ===================================

_event_sink = None


def set_event_sink(sink):
    global _event_sink
    _event_sink = sink


async def emit_event(data: dict):
    if _event_sink is None:
        return
    result = _event_sink(data)
    if asyncio.iscoroutine(result):
        await result


def say(msg="", end="\n", flush=False):
    text = str(msg)
    print(text, end=end, flush=flush)
    if _event_sink is not None and end == "\n":
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(emit_event({"type": "log", "message": text}))
        except RuntimeError:
            pass


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
        say("\n📋 Como deseja continuar?")
        say("  (r) Recomeçar — APAGA os tópicos do destino e copia tudo de novo")
        if tem_sync:
            say("  (i) Incremental — copia só mensagens novas")
        say("  (s) Semear sync — registra IDs da origem sem copiar")
        say("  (a) Abortar")
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
            say("Opção inválida.")

    say("\n📥 Primeira cópia deste par — todo o conteúdo será copiado.")
    say("   Nas próximas vezes você poderá sincronizar só o que for novo.")
    return "full"


async def apagar_todos_topicos_destino(client, to_entity):
    if not await is_forum(client, to_entity):
        say("⚠️ Destino não é um fórum com tópicos — limpeza automática não disponível.")
        return False

    topics = await listar_topicos(client, to_entity)
    if not topics:
        say("Nenhum tópico encontrado no destino.")
        return True

    say(f"\n🗑️ Apagando {len(topics)} tópico(s) do destino…")
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
            say(f"  ✅ Apagado: {title!r}")
            await asyncio.sleep(SLEEP_BETWEEN)
        except FloodWaitError as exc:
            await aguardar_flood(exc)
            await client(
                functions.messages.DeleteTopicHistoryRequest(
                    peer=to_entity,
                    top_msg_id=topic.id,
                )
            )
            apagados += 1
            say(f"  ✅ Apagado: {title!r}")
        except RPCError as exc:
            if "wait" in str(exc).lower() and "seconds" in str(exc).lower():
                await aguardar_flood(exc)
                await client(
                    functions.messages.DeleteTopicHistoryRequest(
                        peer=to_entity,
                        top_msg_id=topic.id,
                    )
                )
                apagados += 1
                say(f"  ✅ Apagado: {title!r}")
            else:
                say(f"  ⚠️ Não foi possível apagar {title!r}: {exc}")
        except Exception as e:
            say(f"  ⚠️ Não foi possível apagar {title!r}: {e}")

    say(f"🗑️ Limpeza concluída ({apagados}/{len(topics)} tópico(s)).")
    return apagados > 0


def confirmar_recomeco(nome_destino: str) -> bool:
    say("\n⚠️  ATENÇÃO: todos os tópicos e mensagens do DESTINO serão apagados.")
    say("   Esta ação não pode ser desfeita pelo script.")
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
    say("\n🌱 Semeando sync a partir da origem (sem copiar mensagens)…")

    if not topics:
        max_id = await obter_max_msg_id_origem(client, from_entity, 1, set())
        registrar_topico_sync(sync_data, pair_key, 1, "Geral", max_id)
        say(f"  Geral: último id registrado = {max_id}")
    else:
        for topic in topics:
            title = topic.title or "Geral"
            max_id = await obter_max_msg_id_origem(
                client, from_entity, topic.id, other_topic_ids
            )
            registrar_topico_sync(sync_data, pair_key, topic.id, title, max_id)
            say(f"  {title!r}: último id registrado = {max_id}")

    save_sync(sync_data)
    say("✅ Sync inicializado. Nas próximas execuções use modo incremental (s).")


def first_time_setup(existing_cfg=None):
    cfg = existing_cfg or {}
    say("\n=== Configuração inicial (será salva em cpgrupo_config.json) ===")

    while True:
        v = input("Informe seu API ID (número criado em my.telegram.org): ").strip()
        if v.isdigit():
            cfg["api_id"] = int(v)
            break
        say("API ID deve ser um número inteiro.")

    v = input("Informe seu API HASH (texto criado em my.telegram.org): ").strip()
    while not v or " " in v:
        say("API HASH inválido (não use espaços).")
        v = input("Informe seu API HASH novamente: ").strip()
    cfg["api_hash"] = v

    save_config(cfg)
    say("✅ Configuração salva em", CONFIG_FILE.name)
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
        say("\nNenhum grupo encontrado na sua conta.")
        return

    say(f"\n{'─' * 76}")
    say(f"{'#':>3}  {'ID':<20}  {'Tipo':<8}  Nome")
    say(f"{'─' * 76}")
    for indice, grupo in enumerate(grupos, 1):
        say(f"{indice:>3}  {grupo['peer_id']:<20}  {grupo['tipo']:<8}  {grupo['nome']}")
    say(f"{'─' * 76}")
    say(f"Total: {len(grupos)} grupo(s)")
    say("Use o número (#), o ID (-100...) ou o nome exato para selecionar.\n")


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
                say("Carregando grupos…")
                grupos = await coletar_grupos(client)
            exibir_grupos(grupos)
            continue

        if entrada.lower() in LISTAR_COMANDOS:
            if grupos is None:
                say("Carregando grupos…")
                grupos = await coletar_grupos(client)
            exibir_grupos(grupos)
            continue

        if entrada.isdigit() and grupos and not entrada.startswith("-"):
            indice = int(entrada)
            if 1 <= indice <= len(grupos):
                escolhido = grupos[indice - 1]
                say(f"Selecionado: {escolhido['nome']} ({escolhido['peer_id']})")
                return escolhido["entity"]

        try:
            entity = await resolve_entity(client, entrada)
            peer_id = utils.get_peer_id(entity)
            nome = getattr(entity, "title", None) or getattr(entity, "first_name", entrada)
            say(f"Selecionado: {nome} ({peer_id})")
            return entity
        except Exception as exc:
            say(f"❌ Não encontrado: {exc}")
            say("Digite 'listar' para ver todos os grupos com ID.")


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
    say("⚙️ Ativando tópicos no grupo de destino…")
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
    say(f"✅ Supergrupo criado: {title!r}")
    say(f"   ID: {peer_id}")
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

        say("Responda s ou n.")


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
            say(f"  ⚠️ Não foi possível fechar o tópico {title!r}: {e}")

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
                say(f"  ⚠️ Não foi possível renomear o tópico Geral: {e}")

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
                say(f"  ⚠️ Não foi possível fechar o tópico Geral: {e}")

        return None

    existing = await buscar_topico_por_titulo(client, to_entity, title)
    if existing:
        say(f"  ↪ Tópico já existe no destino, reutilizando: {title!r}")
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


def _formatar_duracao(total_segundos: int) -> str:
    horas, resto = divmod(max(0, total_segundos), 3600)
    minutos, segundos = divmod(resto, 60)
    if horas:
        return f"{horas:02d}:{minutos:02d}:{segundos:02d}"
    return f"{minutos:02d}:{segundos:02d}"


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
    inicio = datetime.now()
    fim = inicio + timedelta(seconds=seconds + 1)

    say("\n  ═══════════════════════════════════════")
    say("  ⏳ FLOODWAIT — limite temporário do Telegram")
    say(f"  🕐 Início da pausa:  {inicio.strftime('%d/%m/%Y %H:%M:%S')}")
    say(f"  🕑 Retomada prevista: {fim.strftime('%d/%m/%Y %H:%M:%S')}")
    say(f"  ⏱️  Duração total:    {_formatar_duracao(seconds)} ({seconds}s)")
    say("  💡 Não feche o terminal — o script continua sozinho.")
    say("  ═══════════════════════════════════════\n")

    await emit_event({
        "type": "flood_start",
        "total": seconds,
        "remaining": seconds + 1,
        "start": inicio.strftime("%d/%m/%Y %H:%M:%S"),
        "end": fim.strftime("%d/%m/%Y %H:%M:%S"),
        "end_time": fim.strftime("%H:%M:%S"),
    })

    restante = seconds + 1
    while restante > 0:
        linha = (
            f"  ⏳ Aguardando... faltam {_formatar_duracao(restante)} "
            f"| retoma às {fim.strftime('%H:%M:%S')}"
        )
        print(f"\r{linha:<72}", end="", flush=True)
        await emit_event({
            "type": "flood_tick",
            "total": seconds,
            "remaining": restante,
            "end": fim.strftime("%d/%m/%Y %H:%M:%S"),
            "end_time": fim.strftime("%H:%M:%S"),
            "start": inicio.strftime("%d/%m/%Y %H:%M:%S"),
        })
        await asyncio.sleep(1)
        restante -= 1

    say("\r  ✅ Pausa concluída. Retomando cópia…" + " " * 40)
    await emit_event({"type": "flood_end"})


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
        say(f"  {total} mensagens encaminhadas…")
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
            say(f"  Erro em lote -> {e}")
            for mid in ids_buffer[:]:
                try:
                    await encaminhar_com_retry(
                        client, from_entity, to_entity, [mid], dest_top_id
                    )
                    total += 1
                    max_copied_id = max(max_copied_id, mid)
                except Exception as e2:
                    say(f"  Erro id {mid} -> {e2}")
            ids_buffer.clear()

    if ids_buffer:
        try:
            await enviar_buffer()
        except Exception as e:
            say(f"  Erro no envio final -> {e}")
            for mid in ids_buffer[:]:
                try:
                    await encaminhar_com_retry(
                        client, from_entity, to_entity, [mid], dest_top_id
                    )
                    total += 1
                    max_copied_id = max(max_copied_id, mid)
                except Exception as e2:
                    say(f"  Erro id {mid} -> {e2}")

    return total, max_copied_id


async def copiar_comunidade_forum(client, from_entity, to_entity, incremental=False, sync_data=None):
    sync_data = sync_data if sync_data is not None else load_sync()
    pair_key = sync_pair_key(from_entity, to_entity)
    to_entity = await ensure_forum_enabled(client, to_entity)
    topics = await listar_topicos(client, from_entity)

    if not topics:
        say("⚠️ Nenhum tópico encontrado na origem. Copiando mensagens no tópico Geral…")
        title = "Geral"
        min_id = obter_ultimo_id_topico(sync_data, pair_key, 1, title) if incremental else 0
        if incremental and min_id:
            say(f"  Última mensagem copiada: id {min_id}")
        elif incremental and min_id == 0 and await destino_topico_tem_conteudo(client, to_entity, None):
            say("  ⚠️ Destino já tem mensagens sem histórico de sync. Pulando para evitar duplicatas.")
            say("  Use a opção 'semear sync' na próxima execução.")
            return
        total, max_id = await copiar_mensagens_topico(
            client, from_entity, to_entity, 1, None, set(), min_msg_id=min_id
        )
        registrar_topico_sync(sync_data, pair_key, 1, title, max_id)
        save_sync(sync_data)
        if total == 0 and incremental:
            say("  Nenhuma mensagem nova.")
        say(f"\n✅ Cópia concluída. Total: {total} mensagem(ns)\n")
        return

    dest_topics = await listar_topicos(client, to_entity)
    dest_topics_by_id = {t.id: t for t in dest_topics}
    other_topic_ids = {t.id for t in topics if t.id != 1}

    say(f"\n📋 {len(topics)} tópico(s) encontrado(s) na origem.")
    if incremental:
        say("🔄 Modo incremental: copiando apenas mensagens novas por tópico.")
    grand_total = 0

    for index, topic in enumerate(topics, 1):
        title = topic.title or "Geral"
        say(f"\n[{index}/{len(topics)}] Tópico: {title!r}")

        min_id = obter_ultimo_id_topico(sync_data, pair_key, topic.id, title) if incremental else 0
        if incremental and min_id:
            say(f"  Última mensagem copiada: id {min_id}")

        try:
            dest_top_id = await preparar_topico_destino(
                client, to_entity, topic, dest_topics_by_id
            )
            say(f"  top_msg_id destino = {dest_top_id!r}")
        except ChatAdminRequiredError:
            say("  ⚠️ Sem permissão para criar/editar tópicos. Pulando.")
            continue
        except Exception as e:
            say(f"  ❌ Erro ao preparar tópico: {e}")
            continue

        if incremental and min_id == 0:
            tem_conteudo = await destino_topico_tem_conteudo(
                client, to_entity, dest_top_id if topic.id != 1 else None
            )
            if tem_conteudo:
                say("  ⚠️ Tópico já tem mensagens no destino sem histórico de sync.")
                say("  Pulando para evitar duplicatas. Use 'semear sync' na próxima execução.")
                continue

        say("  Iniciando cópia…")
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
                say("  Nenhuma mensagem nova.")
            else:
                say(f"  ✅ Tópico concluído: {total} mensagem(ns)")
        except Exception as e:
            say(f"  ❌ Erro ao copiar tópico: {e}")

        if index < len(topics):
            await asyncio.sleep(PAUSA_ENTRE_TOPICOS)

    say(f"\n✅ Comunidade sincronizada. Total geral: {grand_total} mensagem(ns)\n")


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
    say(f"Tópico no destino: {topic_title!r}")

    try:
        to_entity = await ensure_forum_enabled(client, to_entity)
        top_msg_id = await get_or_create_topic(client, to_entity, topic_title)
        say(f"top_msg_id = {top_msg_id}")
    except ChatAdminRequiredError:
        say("⚠️ Sem permissão para criar tópicos no destino. Encaminhando SEM tópico.")
        top_msg_id = None

    min_id = obter_ultimo_id_topico(sync_data, pair_key, 0, topic_title) if incremental else 0
    if incremental and min_id:
        say(f"Última mensagem copiada: id {min_id}")
        say("🔄 Modo incremental: copiando apenas mensagens novas.")
    elif incremental and min_id == 0 and await destino_topico_tem_conteudo(client, to_entity, top_msg_id):
        say("⚠️ Destino já tem mensagens sem histórico de sync. Pulando para evitar duplicatas.")
        return

    say("Iniciando cópia…")
    total, max_id = await copiar_mensagens_topico(
        client, from_entity, to_entity, None, top_msg_id, min_msg_id=min_id
    )
    registrar_topico_sync(sync_data, pair_key, 0, topic_title, max_id)
    save_sync(sync_data)
    if total == 0 and incremental:
        say("Nenhuma mensagem nova.")
    say(f"✅ Encaminhamento concluído. Total: {total}\n")


async def copiar_origem(client, from_entity, to_entity, mode="full", skip_confirm_rebuild=False):
    sync_data = load_sync()
    pair_key = sync_pair_key(from_entity, to_entity)

    if mode == "seed":
        await semear_sync_da_origem(client, from_entity, to_entity, sync_data)
        return

    if mode == "rebuild":
        nome_destino = getattr(to_entity, "title", None) or "destino"
        if not skip_confirm_rebuild and not confirmar_recomeco(nome_destino):
            say("Operação cancelada.")
            return
        await apagar_todos_topicos_destino(client, to_entity)
        limpar_sync_par(sync_data, pair_key)
        mode = "full"

    incremental = mode == "incremental"
    if await is_forum(client, from_entity):
        say("📂 Origem detectada como comunidade com tópicos.")
        await copiar_comunidade_forum(
            client, from_entity, to_entity, incremental=incremental, sync_data=sync_data
        )
    else:
        say("💬 Origem detectada como grupo/chat simples.")
        await copiar_grupo_simples(
            client, from_entity, to_entity, incremental=incremental, sync_data=sync_data
        )


async def executar_copia(
    client,
    cfg,
    origem_peer_id: int,
    mode: str = "incremental",
    destino_peer_id=None,
    criar_destino: bool = False,
    destino_nome: str = "",
    destino_about: str = "",
    skip_confirm_rebuild: bool = False,
):
    from_entity = await client.get_entity(origem_peer_id)
    if criar_destino:
        nome = destino_nome.strip() or f"{getattr(from_entity, 'title', 'Grupo')} (Cópia)"
        to_entity = await criar_supergrupo_forum(client, nome[:128], destino_about)
        cfg["destino_id"] = utils.get_peer_id(to_entity)
        save_config(cfg)
    else:
        if destino_peer_id is None:
            raise ValueError("Informe o grupo de destino.")
        to_entity = await ensure_forum_enabled(client, await client.get_entity(destino_peer_id))
        cfg["destino_id"] = utils.get_peer_id(to_entity)
        save_config(cfg)

    if mode == "cancel":
        return

    await copiar_origem(
        client,
        from_entity,
        to_entity,
        mode=mode,
        skip_confirm_rebuild=skip_confirm_rebuild,
    )


async def main(reset=False, reset_sync=False):
    if reset_sync and SYNC_FILE.exists():
        SYNC_FILE.unlink()
        say("✅ Histórico de sync apagado (cpgrupo_sync.json).")

    cfg = ensure_config(reset=reset)
    api_id = cfg["api_id"]
    api_hash = cfg["api_hash"]

    async with TelegramClient(SESSION_NAME, api_id, api_hash) as client:
        me = await client.get_me()
        say("\nConectado como", me.username or me.first_name)
        say("Dica: pressione Enter ou digite 'listar' para ver seus grupos com ID.")

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
                    say("Operação cancelada.")
                    continue
                await copiar_origem(client, from_entity, to_entity, mode=mode)
            except Exception as e:
                say(f"❌ Erro ao copiar: {e}")

            repetir = input("\nDeseja copiar outro grupo? (s/n): ").strip().lower()
            if repetir != "s":
                say("Encerrando execução. 👋")
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
    parser.add_argument(
        "--web",
        action="store_true",
        help="Iniciar interface web no navegador.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=WEB_PORT,
        help=f"Porta da interface web (padrão: {WEB_PORT}).",
    )
    args = parser.parse_args()

    if args.web:
        import os
        import uvicorn

        os.environ["CPGRUPO_WEB_PORT"] = str(args.port)
        say(f"Iniciando interface web em http://127.0.0.1:{args.port}")
        uvicorn.run("web_server:app", host="127.0.0.1", port=args.port, log_level="warning")
    else:
        asyncio.run(main(reset=args.reset, reset_sync=args.reset_sync))
