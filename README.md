# Clipes — central de cortes de GTA 6

Plataforma que encontra os melhores momentos em lives e vídeos de GTA 6, sugere cortes com início e fim,
estima o potencial viral, organiza por categoria e prepara o vídeo vertical 1080×1920 para TikTok, Reels e
Shorts. Você revisa e aprova.

- **Backend**: Python 3.11+ · FastAPI · SQLAlchemy (SQLite ou PostgreSQL) · fila de jobs no banco · FFmpeg · OpenCV
- **IA**: Claude (Anthropic) para avaliar cada momento · Whisper local opcional para transcrição
- **Frontend**: React · TypeScript · Vite · Tailwind · TanStack Query

A arquitetura completa está em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

## Colocar no ar (Railway, a partir do GitHub)

1. Entre em railway.com com sua conta do GitHub e assine o plano Hobby.
2. **New Project → Deploy from GitHub repo →** escolha este repositório. O `Dockerfile` e o `railway.json` já configuram tudo.
3. No serviço, **Volume → Mount path `/data`** (guarda banco, vídeos e exportações).
4. **Variables:** `APP_PASSWORD` (senha do painel) e `ANTHROPIC_API_KEY`. Opcionais: `YOUTUBE_API_KEY`, `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`.
5. **Settings → Networking → Generate Domain.** Abra o link; usuário `admin` e a senha definida.

Cada push no `main` publica a nova versão automaticamente.

## Como rodar no Windows (modo fácil)

1. Baixe o projeto: no GitHub, botão verde **Code** → **Download ZIP**, e extraia a pasta.
2. Clique duas vezes em **`instalar.bat`** (na primeira vez ele pode pedir para abrir de novo após instalar programas).
3. Cole sua chave da Anthropic no Bloco de Notas que abrir, salve e feche.
4. Clique duas vezes em **`iniciar.bat`**. O painel abre em http://localhost:8000.

## Como rodar (desenvolvimento)

Pré-requisitos: Python 3.11+, Node 20+ e FFmpeg (`ffmpeg` e `ffprobe` no PATH).

```bash
make setup
```

Edite o `.env` criado (veja a seção abaixo). Depois, em três terminais:

```bash
make api
```

```bash
make worker
```

```bash
make web
```

Abra http://localhost:5173. Para usar só uma porta, rode `make build` e acesse a API em http://localhost:8000,
que passa a servir o painel.

Com Docker (Postgres + API + worker):

```bash
docker compose up -d --build
```

Testes (incluem o pipeline completo com um vídeo gerado pelo FFmpeg):

```bash
make test
```

## O que você precisa configurar

| Serviço | Variáveis no `.env` | Para quê | Custo |
|---|---|---|---|
| **Anthropic (Claude)** — obrigatório | `ANTHROPIC_API_KEY` | Avaliar momentos, escolher início/fim, categoria e notas | Pago por uso |
| YouTube Data API v3 | `YOUTUBE_API_KEY` | Monitorar novos vídeos dos canais | Gratuito dentro da cota |
| Twitch Helix | `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | Monitorar VODs e destaques | Gratuito |
| Whisper (opcional) | `TRANSCRIPTION_PROVIDER=faster_whisper` | Transcrever falas para a IA entender piadas e diálogos | Local (CPU/GPU) |

- **Claude**: console.anthropic.com → API Keys. Modelo e esforço em `AI_MODEL` e `AI_EFFORT`.
- **YouTube**: Google Cloud Console → APIs e serviços → ativar “YouTube Data API v3” → Credenciais → Chave de API.
- **Twitch**: dev.twitch.tv/console → Register Your Application (redirect `http://localhost`) → Client ID e Client Secret.
- **Whisper**: `pip install -r backend/requirements-transcription.txt`. Baixa o modelo na primeira execução.

Sem a chave da Anthropic, a plataforma ingere a mídia e detecta os momentos candidatos pelos sinais, mas não
cria cortes. O job falha com a mensagem “ANTHROPIC_API_KEY não configurada”, e nada é inventado.
A tela **Configurações** mostra o status de cada integração.

## Fluxo de uso

1. **Criadores**: cadastre os criadores (Coringa, Paulinho O Loko, Davy Jones, Alanzoka e Lipão Gamer aparecem
   como sugestão). Informe o @ do YouTube e/ou o login da Twitch e registre a autorização de uso, quando houver.
2. **Descoberta com IA**: com o monitoramento ligado em Automações, novos vídeos de GTA 6 aparecem aqui.
   Envie a mídia autorizada de um vídeo (upload ou link direto de arquivo) ou adicione uma mídia avulsa.
3. O worker prepara a mídia, mede os sinais, detecta a webcam e envia os melhores momentos para o Claude avaliar.
4. **Central de Clipes**: os cortes chegam ordenados por potencial viral, com miniatura, criador, categoria,
   duração, nota e status. Clique em um corte para assistir à prévia 9:16, ver a avaliação e aprovar ou rejeitar.
5. **Editor**: ajuste início e fim na linha do tempo (atalhos `I`/`O`), escolha entre webcam + jogo e tela cheia,
   arraste e redimensione a webcam, ajuste foco e zoom, salve como padrão do criador e exporte.
6. **Exportações**: baixe os MP4 1080×1920 (H.264 + AAC, áudio sincronizado).

## Direitos autorais

A plataforma não baixa vídeos do YouTube, Twitch ou TikTok. O monitoramento lê só os metadados pelas APIs
oficiais. Para cortar, a mídia precisa ser própria, autorizada pelo criador ou licenciada. Cada vídeo registra
a base de direitos, e cada corte mantém o criador e o link da fonte original.

## Estrutura

```
backend/
  app/api/          rotas REST
  app/queue/        fila de jobs
  app/worker/       worker e handlers do pipeline
  app/services/     mídia, sinais, candidatos, IA, pontuação, layout, renderização, fontes
  tests/            testes unitários e de ponta a ponta
frontend/src/
  pages/            as 9 seções do painel
  components/       UI, player 9:16, visualizador de cortes
  lib/              cliente da API, formatação, enquadramento
docs/ARQUITETURA.md
```

Dados e arquivos ficam em `data/` (banco SQLite, mídias, exportações e logs em `data/logs/`). A pasta fica fora do git.
