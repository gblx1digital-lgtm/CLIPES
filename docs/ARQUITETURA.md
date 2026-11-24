# Arquitetura — Plataforma de Clipes GTA 6

## Visão geral

```
                    ┌──────────────────────────── Frontend (React + Vite) ───────────────────────────┐
                    │ Dashboard · Central de Clipes · Descoberta · Criadores · Categorias · Editor   │
                    │ Exportações · Automações · Configurações   (prévia 9:16 em canvas, sem servidor)│
                    └───────────────────────────────┬─────────────────────────────────────────────────┘
                                                    │ REST /api (JSON, upload, streaming com Range)
┌───────────────────────────────────────────────────▼────────────────────────────────────────────────┐
│ API (FastAPI) — app/main.py, app/api/*                                                              │
│ Só valida, grava e enfileira. Nunca processa vídeo na requisição → a interface nunca trava.        │
└───────────────┬──────────────────────────────────────────────────────────────┬─────────────────────┘
                │ SQLAlchemy                                                   │ arquivos
        ┌───────▼────────┐        claim atômico           ┌─────────────────────▼──────────────────┐
        │ Banco          │◄──────────────────────────────►│ Worker(s) — app/worker/*               │
        │ SQLite / PG    │  jobs, vídeos, cortes,          │ monitor_creator → ingest_media →       │
        │ (fila incluída)│  exportações, atividades        │ analyze_video → render_export          │
        └────────────────┘                                 └──┬──────────┬───────────┬──────────────┘
                                                              │          │           │
                                         APIs oficiais ◄──────┘   FFmpeg/OpenCV   Claude (Anthropic)
                                         YouTube / Twitch          (sinais, render)  + Whisper opcional
```

| Camada | Pasta | Responsabilidade |
|---|---|---|
| Frontend | `frontend/src` | Painel. `lib/layout.ts` replica o enquadramento do backend para a prévia 9:16 ser idêntica ao MP4 final. |
| API | `backend/app/api` | Rotas REST, validação, upload em streaming, servir mídia com `Range`. |
| Fila | `backend/app/queue/jobs.py` | Fila persistida no banco: prioridade, tentativas, cancelamento, heartbeat e recuperação de jobs órfãos. |
| Worker | `backend/app/worker` | Executa os jobs e agenda o monitoramento conforme a frequência configurada. |
| Fontes | `backend/app/services/sources` | YouTube Data API v3 e Twitch Helix (só metadados). |
| Processamento de vídeo | `services/media.py`, `signals.py`, `layout.py`, `render.py` | ffprobe/ffmpeg, energia do áudio, cortes de cena, detecção de webcam, renderização 1080×1920. |
| IA | `services/ai_analysis.py`, `transcription.py`, `candidates.py`, `scoring.py` | Candidatos por sinais → avaliação do Claude com quadros e transcrição → nota viral. |
| Dados | `backend/app/models.py` | Criadores, vídeos-fonte, cortes, exportações, jobs, atividades, configurações. |

## Pipeline de descoberta

1. **Monitorar** (`monitor_creator`): o worker consulta as APIs oficiais na frequência definida em Automações,
   filtra títulos pelas palavras-chave de GTA 6 e registra vídeos novos (somente metadados e link).
2. **Mídia autorizada** (`ingest_media`): o arquivo entra por upload ou link direto de arquivo, sempre com a
   base de direitos registrada (próprio / autorizado / licenciado). Links de páginas do YouTube, Twitch, TikTok etc.
   são recusados. Formatos que o navegador não reproduz são convertidos (remux sem perda quando possível).
3. **Sinais** (`analyze_video`, sem custo de IA):
   - energia do áudio em janelas de 0,5 s com z-score robusto (gritos, risadas, explosões);
   - mudanças de cena via filtro `scene` do ffmpeg (ação, perseguições);
   - transcrição opcional (Whisper) com contagem de expressões de reação;
   - detecção de webcam: rosto estável no mesmo lugar em 12 quadros amostrados (OpenCV).
4. **Candidatos** (`candidates.py`): picos combinados com supressão de não-máximos. Cada candidato tem um gancho
   (pico) a ~30% do corte e uma janela de contexto maior para a IA escolher o recorte exato.
5. **IA** (`ai_analysis.py`): o Claude recebe, por candidato, quadros com timestamp, sinais medidos e a transcrição.
   Devolve JSON validado por schema: manter ou descartar, início/fim, título interno, resumo, gancho, categoria e
   8 notas (0–10). Os limites de duração são reforçados no código mesmo se a IA errar.
6. **Pontuação** (`scoring.py`): `0,85 × critérios da IA + 0,15 × intensidade dos sinais` → 0–100.
   Alto ≥ 75 · Médio ≥ 50 · Baixo < 50. Abaixo da nota mínima configurada, o corte é descartado.
7. **Seleção**: ordena por nota (categorias prioritárias +5 só para desempate de seleção), respeita máximo por vídeo
   e por dia, evita sobreposição com cortes existentes, gera miniatura já no enquadramento 9:16.
8. **Revisão**: por padrão todo corte fica “Aguardando revisão”. No modo automático, só cortes acima da nota
   configurada são aprovados sozinhos.
9. **Exportação** (`render_export`): MP4 H.264 + AAC 1080×1920, corte preciso (seek + reencode), `faststart`.

## Enquadramento vertical

- `split`: webcam numa faixa no topo (18–45% da altura, padrão 30%) + gameplay embaixo.
- `full`: gameplay em tela cheia com recorte 9:16, foco horizontal e zoom ajustáveis.
- Webcam: padrão salvo do criador › detecção automática › tela cheia. O editor permite arrastar/redimensionar.
- Sem textos, legendas, emojis, marcas d'água, transições ou efeitos: o filtro do ffmpeg é só `crop` + `scale` (lanczos) + `vstack`.

## Decisões

- **Fila no banco, não Redis**: menos infraestrutura, auditável pelo painel, idêntica em SQLite e Postgres.
  O claim é um `UPDATE ... WHERE status='queued'` atômico; vários workers podem rodar em paralelo.
- **Heartbeat em thread separada**: jobs longos continuam “vivos”; se um worker morrer, o job volta para a fila
  depois de `JOB_STALE_MINUTES`.
- **Erros definitivos x temporários**: falta de chave, falta de direitos ou arquivo inválido falham na hora com
  mensagem clara; erros de rede/API são tentados de novo com espera crescente.
- **Sinais antes da IA**: horas de live viram ~10–16 janelas; o custo de IA fica proporcional ao número de
  momentos, não à duração da live.
- **Segredos só no `.env`**: o painel mostra o que está configurado, nunca os valores.

## Direitos autorais

- Monitoramento: só metadados via APIs oficiais.
- Processamento: só mídia com base de direitos registrada; “autorizado” exige o criador marcado como autorizado.
- Rastreabilidade: cada vídeo guarda a base de direitos e o registro; cada corte guarda criador, título e link da fonte.

## Pontos de extensão

| Quero… | Onde |
|---|---|
| Nova plataforma de monitoramento (Kick, etc.) | novo módulo em `services/sources/` + chamada em `handle_monitor_creator` |
| Outro motor de transcrição | `services/transcription.py` |
| Novos sinais (ex.: chat da live, detecção de risada) | `services/signals.py` + peso em `candidates.py` |
| Mudar os critérios/pesos da nota | `services/scoring.py` (o painel lê de `/api/scoring`) |
| Publicação automática (TikTok/YouTube) | novo tipo de job em `queue/jobs.py` + handler, usando as APIs oficiais de upload |
| Migrações de schema | hoje `create_all`; para evoluir o schema em produção, adicionar Alembic |
