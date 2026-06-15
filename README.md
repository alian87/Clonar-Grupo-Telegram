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
- **Sincronização incremental** — na 2ª execução, copia só mensagens novas por tópico.
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

### 🔄 Sincronizar só conteúdo novo

Na **segunda cópia** do mesmo par origem → destino, o script detecta a cópia anterior e pergunta:

```
Copiar apenas conteúdo NOVO? (s/n) [s]:
```

- **s** (padrão) → copia só mensagens que ainda não foram encaminhadas, tópico por tópico.
- **n** → recopia tudo do zero (útil se algo deu errado).

O progresso fica salvo em `cpgrupo_sync.json` (local, não commitar).

### 🔄 Reconfiguração

```bash
python CopiarGrupo.py --reset
```

Isso apaga `cpgrupo_config.json` e solicita novamente API ID e API HASH.

## 🧱 Estrutura de arquivos

| Arquivo | Função |
|----------|--------|
| **`CopiarGrupo.py`** | Script principal de clonagem. |
| **`requirements.txt`** | Dependências Python (Telethon). |
| **`cpgrupo_config.json`** | Armazena `api_id` e `api_hash` (gerado localmente). |
| **`session_forward.session`** | Sessão da sua conta no Telegram (gerado localmente). |
| **`README.md`** | Instruções de uso. |

## ⚠️ Avisos e boas práticas

1. Use somente em grupos nos quais você participa e tem permissão.
2. Respeite os Termos de Uso do Telegram.
3. O script usa a User API (sua conta), não Bot API.
4. Grupos muito grandes podem gerar `FloodWait` — o script aguarda automaticamente.
5. Tópicos fechados na origem só serão copiados se sua conta tiver acesso a eles.
6. Ícones personalizados (emoji premium) podem não ser replicados sem Telegram Premium.

## 🧠 Exemplo de uso

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

## 🙏 Créditos

Projeto original por [replicant026](https://github.com/replicant026/Clonar-Grupo-Telegram).

Este fork utiliza [**Telethon**](https://github.com/LonamiWebs/Telethon) — MIT License.
