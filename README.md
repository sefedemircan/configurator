# Virtual Try-On API

## Quick start

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# .env içine OPENROUTER_API_KEY ekleyin
```

### Streamlit test arayüzü

```bash
streamlit run streamlit_app.py
```

### Streamlit Community Cloud

Repo GitHub’da (`sefedemircan/otom-ai-configurator`). Deploy:

1. [share.streamlit.io/deploy](https://share.streamlit.io/deploy?repository=sefedemircan/otom-ai-configurator&branch=main&mainModule=streamlit_app.py) — repository `sefedemircan/otom-ai-configurator`, branch `main`, main file `streamlit_app.py`
2. Advanced settings → Secrets:

```toml
OPENROUTER_API_KEY = "sk-or-..."
OPENROUTER_VISION_MODEL = "google/gemini-3-pro-image-preview"
OPENROUTER_IMAGE_MODEL = "google/gemini-3-pro-image-preview"
```

Anahtar asla git’e eklenmez. Cloud, `st.secrets` ve ortam değişkeni olarak okur.

### FastAPI servisi

```bash
uvicorn app.main:app --reload --port 8000
```

## Pipeline

| Adım | Açıklama |
|------|----------|
| 1. Vision | Fotoğraftaki görünür koltukları tespit eder (ön/arka/4 koltuk) |
| 2. Ürün kompoziti | Configurator katmanlarından veya Shopify URL'den referans görsel |
| 3. Generatif try-on | Her görünür koltuk için sırayla Gemini Image çağrısı |

## Environment

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | Vision + image generation |
| `OPENROUTER_VISION_MODEL` | Koltuk tespiti (varsayılan: `google/gemini-3-pro-image-preview`) |
| `OPENROUTER_IMAGE_MODEL` | Try-on görüntü modeli (varsayılan: `google/gemini-3-pro-image-preview`) |
| `TRYON_API_KEY` | Opsiyonel API key koruması |

## API

- `GET /health`
- `POST /api/v1/tryon/composite`
- `POST /api/v1/tryon/composite/stream` (SSE)

`seat_target`: `auto` (varsayılan) veya tek koltuk override (`front_driver`, `front_passenger`, `rear_left`, `rear_right`, `rear_bench`).

## Docker

```bash
docker build -t otom-tryon .
docker run -p 8000:8000 --env-file .env otom-tryon
```
