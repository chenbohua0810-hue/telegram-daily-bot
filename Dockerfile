FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

COPY crypto_copy_trader/requirements.txt /app/crypto_copy_trader/requirements.txt
RUN pip install --no-cache-dir -r /app/crypto_copy_trader/requirements.txt

COPY crypto_copy_trader /app/crypto_copy_trader
RUN python -c "import pathlib, shutil; app = pathlib.Path('/app/crypto_copy_trader'); [shutil.rmtree(app / name) for name in ('config','execution','main','models','monitors','reporting','storage','wallet_scorer') if (app / f'{name}.py').exists() and (app / name).is_dir()]"

RUN chown -R appuser:appuser /app
USER appuser

WORKDIR /app/crypto_copy_trader
VOLUME /app/crypto_copy_trader/data

CMD ["python", "main.py"]
