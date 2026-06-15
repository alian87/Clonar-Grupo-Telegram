# 📦 Telegram Grupo Cloner (com suporte a tópicos)

Script em **Python + Telethon** para **clonar automaticamente comunidades do Telegram com tópicos**, copiando cada tópico da origem para um tópico correspondente no destino — com o mesmo nome, ícone e estado (aberto/fechado).

Também é possível copiar grupos simples (sem tópicos) para um único tópico no destino.

-------------

### 🚀 Recursos

- **Clona comunidades inteiras com tópicos** — cada tópico da origem vira um tópico no destino.
- **Cria o supergrupo de destino automaticamente** — não precisa criar o grupo manualmente.
- Copia **mensagens, mídias e documentos** preservando a ordem cronológica.
- Preserva **nome, ícone e estado fechado** dos tópicos (quando permitido pela API).
- **Oculta os autores originais** (`drop_author=True`).
- Encaminhamento em **lotes** (reduz risco de `FloodWait`).
- **Armazena credenciais** (`api_id`, `api_hash`) no arquivo `cpgrupo_config.json`.
- **Lista seus grupos com ID** — exibe todos os grupos da conta para facilitar a seleção.
- **Sincronização incremental** — nas próximas execuções, copia só o que mudou (mensagens novas e tópicos novos).
- Permite copiar **vários grupos em sequência** sem reiniciar o script.

----

### ⚙️ Requisitos

- **Python 3.10 ou superior**
- Conta Telegram válida (com número verificado)
- Biblioteca **Telethon**
- Permissão de leitura na comunidade de origem
- Permissão de administrador no destino (ou crie um grupo novo — você será admin automaticamente)

----

### 🧩 Configuração inicial

1. Instale o Python.

2. Instale as dependências:

	```bash
	python -m pip install -r requirements.txt
	```

3. Crie sua API em [https://my.telegram.org](https://my.telegram.org) → *API Development Tools*

## ▶️ Execução

1. Abra o terminal na pasta do projeto:

```bash
cd C:\Users\seuusuario\Documentos\Clonar-Grupo-Telegram
```

2. Rode o script:

```bash
python CopiarGrupo.py
```

### Na **primeira execução**, o script solicitará:

1. **API ID** — obtido em [https://my.telegram.org](https://my.telegram.org)
2. **API HASH** — exibido junto do seu API ID

Esses dados serão salvos em `cpgrupo_config.json`.

> ⚠️ Mantenha este arquivo privado! Ele contém credenciais da API do Telegram.

### Em cada cópia, o script:

1. **Exibe todos os seus grupos** com número, ID (`-100...`) e tipo (Grupo ou Fórum).
2. Pede a **origem** — use o número da lista, o ID, @username ou nome exato. Digite `listar` para ver a lista novamente.
3. Pede o **destino** — se deseja **criar um novo supergrupo** com tópicos:
   - **s** → informa o nome (sugestão: `Nome Original (Cópia)`) e o script cria o grupo automaticamente.
   - **n** → seleciona um grupo existente da lista (com tópicos habilitados).

4. Detecta se a origem é uma **comunidade com tópicos**:
   - **Com tópicos** → clona cada tópico separadamente (`# BATE PAPO`, `NOVIDADE`, etc.).
   - **Sem tópicos** → copia tudo para um único tópico com o nome do grupo.

Ao final, pergunta se deseja copiar outro grupo.

---

## 🔄 Sincronização incremental (copiar só o que é novo)

Depois da **primeira cópia completa** entre um par de grupos (origem → destino), o script passa a oferecer o modo incremental.

### Quando aparece

Na segunda vez (ou depois) que você copiar **o mesmo par**, o script exibe um menu:

```
📋 Como deseja continuar?
  (r) Recomeçar — APAGA os tópicos do destino e copia tudo de novo
  (i) Incremental — copia só mensagens novas
  (s) Semear sync — registra IDs da origem sem copiar
  (a) Abortar
Escolha [i]:
```

### O que cada opção faz

| Resposta | Comportamento |
|----------|---------------|
| **r** | **Recomeçar** — apaga todos os tópicos do destino e copia tudo de novo |
| **i** (padrão com sync) | Modo incremental — copia só o que ainda não foi encaminhado |
| **s** | Semear sync — registra IDs da origem sem copiar mensagens |
| **a** | Abortar |

### O que é sincronizado no modo incremental

| Situação na origem | O que o script faz no destino |
|--------------------|-------------------------------|
| **Mensagens novas** em tópico que já existia | Encaminha só as mensagens com ID maior que a última copiada |
| **Tópico novo** criado na origem | Cria o tópico correspondente no destino e copia **todas** as mensagens dele |
| **Tópico sem novidades** | Exibe `Nenhuma mensagem nova.` e segue para o próximo |
| **Grupo simples** (sem fórum) | Mesma lógica: só mensagens novas desde a última sincronização |

### Como o script sabe o que já foi copiado

O progresso é salvo localmente em `cpgrupo_sync.json`, organizado assim:

```json
{
  "pairs": {
    "-1002761889423:-1004497720243": {
      "updated_at": "2026-06-15 14:30 UTC",
      "topics": {
        "BATE PAPO": {
          "last_msg_id": 8542,
          "source_topic_id": 1
        },
        "NOVIDADE": {
          "last_msg_id": 12001,
          "source_topic_id": 3
        }
      }
    }
  }
}
```

- **Chave do par:** `ID_origem:ID_destino`
- **Chave do tópico:** nome exato do tópico na origem
- **last_msg_id:** ID da última mensagem já encaminhada daquele tópico

> ⚠️ **Não apague** `cpgrupo_sync.json` se quiser continuar sincronizando. Se apagar, a próxima execução será tratada como primeira cópia daquele par.

> ⚠️ **Não commite** `cpgrupo_sync.json` — é específico da sua máquina.

### Passo a passo para sincronizar

1. Rode `python CopiarGrupo.py`
2. Selecione a **mesma origem** de antes
3. Selecione o **mesmo destino** de antes (`n` → escolha o grupo existente)
4. Responda **s** em `Copiar apenas conteúdo NOVO?`
5. Aguarde — só tópicos com novidades serão processados

### Exemplo de saída (modo incremental)

```bash
🔄 Cópia anterior detectada para este par de grupos (2026-06-15 14:30 UTC).
Copiar apenas conteúdo NOVO? (s/n) [s]: s

📂 Origem detectada como comunidade com tópicos.
🔄 Modo incremental: copiando apenas mensagens novas por tópico.

📋 19 tópico(s) encontrado(s) na origem.

[1/19] Tópico: 'BATE PAPO'
  Última mensagem copiada: id 8542
  ↪ Tópico já existe no destino, reutilizando: 'BATE PAPO'
  Iniciando cópia…
  Nenhuma mensagem nova.

[2/19] Tópico: 'NOVIDADE'
  Última mensagem copiada: id 12001
  Iniciando cópia…
  8 mensagens encaminhadas…
  ✅ Tópico concluído: 8 mensagem(ns)

[19/19] Tópico: 'PAINEL NOVO 2026'
  Iniciando cópia…
  45 mensagens encaminhadas…
  ✅ Tópico concluído: 45 mensagem(ns)

✅ Comunidade sincronizada. Total geral: 53 mensagem(ns)
```

Neste exemplo:
- `BATE PAPO` não tinha mensagens novas → pulado
- `NOVIDADE` tinha 8 mensagens novas → copiadas
- `PAINEL NOVO 2026` é um **tópico novo** na origem → criado no destino e copiado por completo

### Limitações do modo incremental

- **Não detecta mensagens editadas** na origem — só conteúdo novo
- **Não remove mensagens apagadas** no destino se foram apagadas na origem
- **Não reordena** mensagens já copiadas
- Se você responder **n** (cópia completa), as mensagens serão **duplicadas** no destino

### Como forçar uma cópia completa de novo

**Opção 1 — na execução:** responda **n** quando perguntado sobre conteúdo novo e confirme que aceita duplicar.

**Opção 2 — apagar o histórico:** delete `cpgrupo_sync.json` ou rode:

```bash
python CopiarGrupo.py --reset-sync
```

### Mensagens duplicadas no destino

Se o destino tiver **mais mensagens** que a origem (ex.: 2712 no seu grupo vs 2013 no original), as causas mais comuns são:

1. **Cópia completa rodada mais de uma vez** (antes do sync existir ou respondendo `n`)
2. **Primeira cópia feita antes** do `cpgrupo_sync.json` — na segunda execução tudo foi copiado de novo
3. **Responder `n`** em "copiar apenas conteúdo novo" — recopia tudo e duplica

#### Como corrigir (ex.: SCRIPTS COMPARTILHADA)

**Passo 1 — Semear o sync sem copiar nada** (recomendado se o destino já está quase completo):

```bash
python CopiarGrupo.py
```

- Mesma origem e mesmo destino
- Quando aparecer a opção, escolha **(s) Semear sync sem copiar**

Isso registra o último ID de cada tópico da origem **sem encaminhar mensagens**. Da próxima vez, o modo incremental (`s`) copia só o que for novo.

**Passo 2 — Recomeçar do zero (recomendado se há muitas duplicatas):**

```bash
python CopiarGrupo.py
```

- Mesma origem e destino
- Escolha **(r) Recomeçar**
- Digite **APAGAR** para confirmar

O script apaga todos os tópicos do destino e copia tudo de novo, sem duplicatas.

**Alternativa manual:** apague os tópicos no Telegram e rode uma cópia completa com `--reset-sync`.

---

### 🔄 Reconfiguração da API

```bash
python CopiarGrupo.py --reset
```

Isso apaga `cpgrupo_config.json` e solicita novamente API ID e API HASH.

Para apagar só o histórico de sincronização:

```bash
python CopiarGrupo.py --reset-sync
```

## 🧱 Estrutura de arquivos

| Arquivo | Função |
|----------|--------|
| **`CopiarGrupo.py`** | Script principal de clonagem. |
| **`requirements.txt`** | Dependências Python (Telethon). |
| **`cpgrupo_config.json`** | Armazena `api_id` e `api_hash` (gerado localmente). |
| **`cpgrupo_sync.json`** | Histórico de sincronização incremental por par de grupos e tópico (gerado localmente). |
| **`session_forward.session`** | Sessão da sua conta no Telegram (gerado localmente). |
| **`.gitignore`** | Impede commit de credenciais, sessão e histórico de sync. |
| **`README.md`** | Instruções de uso. |

## ⚠️ Avisos e boas práticas

1. Use somente em grupos nos quais você participa e tem permissão.
2. Respeite os Termos de Uso do Telegram.
3. O script usa a User API (sua conta), não Bot API.
4. Grupos muito grandes podem gerar `FloodWait` — o script aguarda automaticamente.
5. Tópicos fechados na origem só serão copiados se sua conta tiver acesso a eles.
6. Ícones personalizados (emoji premium) podem não ser replicados sem Telegram Premium.
7. No modo incremental, use sempre o **mesmo par** origem → destino para o histórico funcionar.
8. Arquivos locais sensíveis: `cpgrupo_config.json`, `session_forward.session` e `cpgrupo_sync.json`.

## 🧠 Exemplo: primeira cópia (completa)

```bash
python CopiarGrupo.py
Conectado como usuario
Dica: pressione Enter ou digite 'listar' para ver seus grupos com ID.

  #  ID                    Tipo      Nome
  1  -1002761889423        Fórum     SCRIPTS E AMIGOS
  2  -1004497720243        Fórum     SCRIPTS DECO

Selecione a ORIGEM a copiar:
> 1
Selecionado: SCRIPTS E AMIGOS (-1002761889423)

Deseja CRIAR um novo supergrupo com tópicos como destino? (s/n): s
Nome do novo supergrupo [SCRIPTS E AMIGOS (Cópia)]: SCRIPTS DECO
Descrição do grupo (opcional, Enter para pular): Scripts, apks e ferramentas
✅ Supergrupo criado: 'SCRIPTS DECO'
   ID: -1004497720243

📂 Origem detectada como comunidade com tópicos.

📋 13 tópico(s) encontrado(s) na origem.

[1/13] Tópico: '# BATE PAPO'
  top_msg_id destino = 2
  Iniciando cópia…
  100 mensagens encaminhadas…
  ✅ Tópico concluído: 156 mensagem(ns)

[2/13] Tópico: 'NOVIDADE'
  ...

✅ Comunidade clonada. Total geral: 4523 mensagem(ns)

Deseja copiar outro grupo? (s/n): n
Encerrando execução. 👋
```

## 🧠 Exemplo: sincronizar depois (só novidades)

Use quando a origem ganhar mensagens ou tópicos novos e o destino já existir:

```bash
python CopiarGrupo.py

Selecione a ORIGEM a copiar:
> 1
Selecionado: SCRIPTS E AMIGOS (-1002761889423)

Deseja CRIAR um novo supergrupo com tópicos como destino? (s/n): n

Selecione o grupo DESTINO:
> 2
Selecionado: SCRIPTS DECO (-1004497720243)

🔄 Cópia anterior detectada para este par de grupos (2026-06-15 14:30 UTC).
Copiar apenas conteúdo NOVO? (s/n) [s]: s

📂 Origem detectada como comunidade com tópicos.
🔄 Modo incremental: copiando apenas mensagens novas por tópico.

[5/19] Tópico: 'SCRIPTS 2026'
  Última mensagem copiada: id 3300
  Iniciando cópia…
  12 mensagens encaminhadas…
  ✅ Tópico concluído: 12 mensagem(ns)

✅ Comunidade sincronizada. Total geral: 12 mensagem(ns)
```

## 🙏 Créditos

Projeto original por [replicant026](https://github.com/replicant026/Clonar-Grupo-Telegram).

Este fork utiliza [**Telethon**](https://github.com/LonamiWebs/Telethon) — MIT License.
