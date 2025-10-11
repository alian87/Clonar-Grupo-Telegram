# 📦 Telegram Grupo Cloner (com suporte a tópicos)

Script em **Python + Telethon** para **copiar automaticamente todo o conteúdo de um grupo do Telegram para outro**, criando **um novo tópico** no grupo de destino com o **mesmo nome do grupo de origem**.

O objetivo é facilitar **backups, migração ou arquivamento de grupos**, preservando a ordem das mensagens, textos e mídias — tudo dentro de um tópico próprio no destino.

-------------

### 🚀 Recursos

- Copia **mensagens, mídias e documentos** de qualquer grupo para outro.  
- Cria **um novo tópico** no grupo de destino com o nome do grupo de origem.  
- **Oculta os autores originais** (`drop_author=True`), tornando o conteúdo anônimo.  
- Suporte a **supergrupos com tópicos habilitados**.  
- Encaminhamento em **lotes** (reduz risco de `FloodWait`).  
- **Armazena credenciais** (`api_id`, `api_hash`, `destino_id`) no arquivo `cpgrupo_config.json`, pedindo apenas na primeira execução.  
- Permite copiar **vários grupos em sequência** sem reiniciar o script.

----

### ⚙️ Requisitos

- **Python 3.14 ou superior**  
- Conta Telegram válida (com número verificado)  
- Biblioteca **Telethon**

----

### 🧩 Configuração inicial

1. Instale o python

2. Instale o Telethon via `pip`:

	```bash
	python -m pip install telethon
	```
3.  Crie sua API em  [https://my.telegram.org](https://my.telegram.org) → *API Development Tools*

4. Crie um Grupo no Telegram e Habilite **Tópicos**

## ▶️ Execução

### **Para rodar o script:**
1. Abra o CMD e vá até a pasta onde salvou o arquivo: Exemplo: 

```bash
	cd C:\Users\seuusuario\Documentos\Clonar-Grupo-Telegram
```

2. Rode o script: 
```bash
	python CopiarGrupo.py
```

### Na **primeira execução**, o script solicitará:

1. **API ID** – obtido em [https://my.telegram.org](https://my.telegram.org) → *API Development Tools*  
2. **API HASH** – exibido junto do seu API ID (o valor é visível no terminal).  
3. **ID do grupo de destino** – no formato `-100xxxxxxxxxx` (precisa ser um **supergrupo com tópicos ativados**).

Esses dados serão salvos automaticamente no arquivo `cpgrupo_config.json`, como no exemplo:

```json
  "api_id": 12345678,
  "api_hash": "abcdef1234567890abcdef1234567890",
  "destino_id": -1009876543210
```


>⚠️ Mantenha este arquivo privado!
>
>Ele contém suas credenciais de acesso à API do Telegram, associadas à sua conta.


### Nas **próximas execuções** 

1. O script se conecta à sua conta do Telegram usando a sessão salva (session_forward.session).
2. Pergunta o ID ou Nome Exato do grupo de origem (exemplo: -1001122334455 ou Grupo a ser copiado).
3. Cria automaticamente um tópico no grupo de destino com o mesmo nome do grupo de origem.
4. Copia todas as mensagens em ordem cronológica para dentro desse tópico, ocultando o autor original.

Ao final, pergunta:
```bash
copiar outro grupo? (s/n)
```
> s → permite copiar outro grupo.
> 
> n → encerra o programa.

### 🔄 Reconfiguração
Para refazer a configuração (alterar o grupo de destino ou suas credenciais da API):

```bash
python CopiarGrupo.py --reset
```

Isso apaga o arquivo `cpgrupo_config.json`e solicita novamente os dados.

## 🧱 Estrutura de arquivos

📂 Clonar-Grupo-Telegram

| Arquivo | Função |
|----------|--------|
| **`CopiarGrupo.py`** | Script principal que executa a cópia de mensagens e cria os tópicos no grupo destino. |
| **`cpgrupo_config.json`** | Armazena o `api_id`, `api_hash` e `destino_id`, evitando que sejam digitados novamente. |
| **`session_forward.session`** | Sessão persistente da sua conta no Telegram (criada automaticamente pelo Telethon). |
| **`README.md`** | Documento de instruções, instalação e uso do projeto. |

> ⚠️ **Importante:** mantenha os arquivos `cpgrupo_config.json` e `session_forward.session` em local seguro.
> 
> Pois ambos contêm informações de autenticação da sua conta do Telegram.

----
## ⚠️ Avisos e boas práticas

1. Use somente em grupos nos quais você participa.
2. Respeite os Termos de Uso do Telegram — evite automatizar spam ou cópia de conteúdos sem permissão.
3. O script utiliza a User API, não a Bot API, ou seja: age como a sua própria conta.
4. Evite copiar grupos muito grandes de uma vez; o Telegram pode impor FloodWait se o envio for muito rápido.
5. O destino precisa ser um supergrupo com tópicos ativados (Configurações → Recursos → Ativar Tópicos).
6. Caso o destino não permita criar tópicos, as mensagens serão enviadas no feed principal.

## 🧠 Exemplo de uso

```bash
C:\Users\User\Documentos\ python CopiarGrupo.py
Conectado como user
Informe o ID (-100...), @username, ou nome exato do chat de ORIGEM: -112345678910
Tópico no destino: 'Grupo Exemplo'
top_msg_id = 1501
Iniciando cópia…
100 mensagens encaminhadas…
200 mensagens encaminhadas…
✅ Encaminhamento concluído. Total: 356

Deseja copiar outro grupo? (s/n): s```

## 🙏 Créditos e agradecimentos

Este projeto utiliza a biblioteca [**Telethon**](https://github.com/LonamiWebs/Telethon),  
um cliente Python open-source para a API do Telegram, licenciado sob a **MIT License**.

Agradecimentos especiais à comunidade Telethon por tornar possível o uso da API de forma estável e acessível.

> Telethon © 2015–2025 Lonami Exo — Licensed under the MIT License  
> [https://github.com/LonamiWebs/Telethon](https://github.com/LonamiWebs/Telethon)
